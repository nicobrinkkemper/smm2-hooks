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

from autotile import autotile_ground, slope_surface

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
OBJ_P_SWITCH = 18
OBJ_ON_OFF_SWITCH = 99
OBJ_DOTTED_LINE = 100
OBJ_FIRE_FLOWER = 34
OBJ_SUPER_STAR = 35
OBJ_MUNCHER = 57
OBJ_NOTE_BLOCK = 23    # Note block (music block is the same id with a flag)
OBJ_DOOR = 55          # Door; doors pair 2k with 2k+1 WITHIN one area
OBJ_PIPE = 9           # Warp pipe; pipes pair by link (bits 20-23) and are
                       # what crosses between the overworld and the subworld.
                       # Flag words copied off The Lost Woods' own linked pair:
PIPE_UP_LINK1 = 0x6140040     # mouth up (bits 5-6 = 2), link 1
PIPE_RIGHT_LINK1 = 0x6140000  # mouth right (bits 5-6 = 0), link 1

# Object flags (community BCD sheet, "Flags for Objects"). 0x40 and 0x6000000
# are set on every object; the generator's default 0x06000040 is exactly that.
FLAG_WINGS = 0x2
FLAG_DESCENDING = 0x100000  # a slope that descends to the right
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
        # A vertical area: orientation byte (area+0x03) 1, and the area's own
        # height instead of the 27 rows a horizontal area gets. The camera
        # scrolls up the column, and the spawner stops widening the view's
        # top and bottom by +-1000 (sub_7100E40D80: that widening is the
        # `if (!vertical)` branch), so what is loaded above and below is the
        # view itself rather than the whole column.
        self.vertical = False
        self.height = 27          # tiles
        # The overworld's liquid (area+0x04..0x07: end height, mode, speed,
        # start height in rows; liquid.md). None leaves the header's zeros,
        # no liquid. A still pool: start == end, mode 0.
        self.liquid = None        # (end_row, mode, speed, start_row)
        # The subworld (area 1). A vertical area has no goal of its own -- the
        # goal lives in the overworld -- so a vertical column is always built
        # here and reached through a door or pipe.
        self.sub_vertical = False
        self.sub_width = 84       # tiles
        self.sub_height = 27
        self.sub_theme = None     # None = the same theme as the overworld
        self.sub_autoscroll = 0   # a vertical area scrolls UPWARD, and the
                                  # scroll moves what is in spawn range with it
        self.sub_objects: List[dict] = []
        self.sub_ground_tiles: List[Tuple[int, int]] = []
        self.sub_tracks: List[dict] = []
        self.ground_tiles: List[Tuple[int, int]] = []   # (x, y); build() picks the ids
        self.start_y = 5  # tiles
        self.goal_y = None  # auto-calculated if None
        # The area header's flag word (area+0x18, level.ksy `unk_flag`): bit 1
        # is night (SMM2Reversing's LevelFormat.md; the uploaded corpus sets it
        # in 9.3% of courses, bit 0 in 0.08%).
        self.area_flag = 0
        
    def add_ground_fill(self, x_start: int, x_end: int, y: int):
        """Add a row of ground tiles from x_start to x_end at height y."""
        for x in range(x_start, x_end + 1):
            self.ground_tiles.append((x, y))

    def add_ground_block(self, x_start: int, x_end: int, y_surface: int, height: int = 5):
        """Add a solid ground block, its top row at y_surface, `height` rows
        tall (stopping at row 0)."""
        for y in range(y_surface, max(y_surface - height, -1), -1):
            self.add_ground_fill(x_start, x_end, y)

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
    
    def add_slope(self, x: int, y: int, rise: int, steep: bool = False,
                  descending: bool = False):
        """Add a slope object, 88 steep or 87 gentle, climbing `rise` rows.

        (x, y) is the box's bottom-left tile; the record sits at the tile's
        centre. The width follows from the rise (slope_width): the game
        writes every steep slope rise + 1 wide, its last column the top end
        cap, and every gentle one 2 * rise wide. Without `descending` it
        rises to the right; with it, flag 0x100000 (uploaded courses: every
        slope of the SMB3 slide 4067530 carries it and descends). Coursebot
        deleted a slope with flags 0x4, 0x8, 0x10, 0x18, 0x20, 0x40000 or
        0x400000 added, ex 1, or child flags 0x10 / 0x20 (2026-09-03).
        """
        self.objects.append({
            'id': OBJ_STEEP_SLOPE if steep else OBJ_SLIGHT_SLOPE,
            'x': x,
            'y': y,
            'width': slope_width(rise, steep),
            'height': rise,
            'flags': 0x06000040 | (FLAG_DESCENDING if descending else 0),
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
        """A free-standing note block (id 23) in tile (x, y): the record at the
        tile's centre, as every one-tile actor (add_actor)."""
        self.add_actor(OBJ_NOTE_BLOCK, x, y, flags=0x06000040 | (FLAG_WINGS if wings else 0))

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
        any object, tile, slope or track reaching the goal area; and a slope
        record the game never writes (slope_errors)."""
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
        for (x, y) in self.ground_tiles:
            if x >= g:
                bad.append(f"ground tile at ({x}, {y}) is in the goal area (x >= {g})")
                break
        for t in getattr(self, 'tracks', []):
            if t['x'] < self.START_AREA_TILES:
                bad.append(f"track ({t['x']}, {t['y']}) box reaches into the start area (x < {self.START_AREA_TILES})")
        for o in self.objects:
            if o['x'] < self.START_AREA_TILES:
                bad.append(f"object id {o['id']} at ({o['x']}, {o['y']}) is in the start area (x < {self.START_AREA_TILES})")
        bad += slope_errors(self.objects, self.ground_tiles)
        bad += slope_errors(self.sub_objects, self.sub_ground_tiles)
        if bad:
            raise ValueError(f"{self.name}: " + "; ".join(bad))

    def unrecorded(self, x: int, y: int) -> bool:
        """Whether the editor tiles the overworld against ground that has no
        record at (x, y): the start and goal areas (a block's column 7 at row
        start_y - 1 is a plain top in editor-made courses, not a left corner,
        and the same on the goal side at goal_y - 1) and the area's edges."""
        goal_y = self.goal_y if self.goal_y else self.start_y
        return ((x < self.START_AREA_TILES and y < self.start_y)
                or (x >= self.goal_area_start() and y < goal_y)
                or _beyond(x, y, self.width, self.height))

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
        data[area + 0x03] = 1 if self.vertical else 0
        struct.pack_into('<i', data, area + 0x08, self.width * 16)
        struct.pack_into('<i', data, area + 0x0C, self.height * 16)
        struct.pack_into('<I', data, area + 0x18, self.area_flag)
        if self.liquid is not None:
            data[area + 0x04], data[area + 0x05], data[area + 0x06], data[area + 0x07] = self.liquid
        
        # NOTE: Do NOT add goal object - game auto-generates from header goal_x/goal_y
        
        _write_area(data, area, self.objects, _tiled(self.ground_tiles, self.unrecorded, self.objects),
                    getattr(self, 'tracks', []))

        # Area 1, the subworld. Vertical areas live here: a vertical area has
        # no goal, the overworld does, so the column is always the sub-area
        # and the player arrives through a door or pipe.
        area1 = 0x2E0E0
        data[area1 + 0x00] = self.sub_theme if self.sub_theme is not None else self.theme_id
        data[area1 + 0x01] = self.sub_autoscroll   # upward in a vertical area
        data[area1 + 0x02] = 1                     # boundary flags (from original)
        data[area1 + 0x03] = 1 if self.sub_vertical else 0
        data[area1 + 0x04] = 1                     # liquid_end_height
        data[area1 + 0x05] = 0                     # liquid_mode
        data[area1 + 0x06] = 0                     # liquid_speed
        data[area1 + 0x07] = 1                     # liquid_start_height (CRITICAL!)
        struct.pack_into('<i', data, area1 + 0x08, self.sub_width * 16)
        struct.pack_into('<i', data, area1 + 0x0C, self.sub_height * 16)
        _write_area(data, area1, self.sub_objects, _tiled(self.sub_ground_tiles,
                    lambda x, y: _beyond(x, y, self.sub_width, self.sub_height), self.sub_objects),
                    self.sub_tracks)

        return bytes(data)


# ═══════════════════════════════════════════════════════════════════════════
# Test Level Definitions
# ═══════════════════════════════════════════════════════════════════════════

TEST_LEVELS = {}

def slope_width(rise: int, steep: bool) -> int:
    """A slope's width from the rows it climbs, as the game writes it: steep
    rise + 1 (the last column is the top end cap), gentle 2 * rise (255
    steep and 235 gentle records in uploaded and editor-saved courses, no
    exception)."""
    return rise + 1 if steep else 2 * rise


def slopes(objects: list) -> list:
    """slope_surface's arguments for each slope record in `objects`."""
    return [(o['x'], o['y'], o.get('width', 1), o.get('height', 1), o['id'] == OBJ_STEEP_SLOPE,
             bool(o.get('flags', 0) & FLAG_DESCENDING))
            for o in objects if o['id'] in (OBJ_STEEP_SLOPE, OBJ_SLIGHT_SLOPE)]


def slope_errors(objects: list, ground: list) -> list:
    """What is wrong with an area's slope records: a width the game never
    writes for the height, a slope under two rows, ground on its surface
    (no game-saved course has a ground tile on one)."""
    tiles = set(ground)
    bad = []
    for slope in slopes(objects):
        x, y, w, h, steep, _ = slope
        at = f"{'steep' if steep else 'gentle'} slope at ({x}, {y}) {w}x{h}"
        if h < 2:
            bad.append(f"{at} is under two rows tall")
        if w != slope_width(h, steep):
            bad.append(f"{at} is not {slope_width(h, steep)} wide")
        on = sorted(tiles & slope_surface(*slope))
        if on:
            bad.append(f"{at} has ground on its surface at {on}")
    return bad


def _beyond(x, y, width, height):
    """Past the area's left, right or top edge, which the editor tiles as ground."""
    return x < 0 or x >= width or y >= height


def _tiled(positions, outside, objects):
    """(x, y, id) ground records, one per position, with the editor's ids;
    the editor counts the slopes among `objects` as ground there."""
    positions = list(dict.fromkeys(positions))
    ids = autotile_ground(positions, outside, slopes(objects))
    return [(x, y, ids[(x, y)]) for (x, y) in positions]


def _write_area(data: bytearray, area: int, objects: list, ground: list,
                tracks: list) -> None:
    """Objects, ground and track records into one area, and its three counts.

    Both areas have the same layout, so the overworld and the subworld are
    written by the same code; only the base offset differs.
    """
    obj_base = area + 0x48
    for i, obj in enumerate(objects):
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

    ground_base = area + 0x247A4
    for i, (x, y, tile_id) in enumerate(ground):
        off = ground_base + i * 4
        data[off + 0] = x
        data[off + 1] = y
        struct.pack_into('<H', data, off + 2, tile_id)

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

    struct.pack_into('<i', data, area + 0x1C, len(objects))
    struct.pack_into('<i', data, area + 0x3C, len(ground))
    struct.pack_into('<i', data, area + 0x40, len(tracks))


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
    b.add_ground_fill(21, 23, 10)
    b.start_y = 5
    b.goal_y = 10
    return b


@test_level(31, "One Steep Slope")
def level_one_slope() -> LevelBuilder:
    """Flat Ground with one steep slope object on the floor."""
    b = LevelBuilder("One Slope", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_slope(12, 5, rise=4, steep=True)
    b.goal_y = 5
    return b


@test_level(33, "Steep Slope Up")
def level_steep_slope_up() -> LevelBuilder:
    """A steep slope rising to the right, drawn into the floor the way the
    editor does it (a course re-saved in the editor has the same shape): the
    slope object at (12, 4) climbs four rows over columns 12..16, its foot
    tile on the floor's row and its last column the top end cap at (16, 7).
    The floor under the ramp stops at row 3, the cap's column at row 6 under
    the cap, and a column from tile 17 with its top at row 7 meets the
    ramp's top. A slope overlapping ground tiles is deleted by Coursebot."""
    b = LevelBuilder("Steep Slope Up", "SMB1", "Ground")
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 15, y_surface=3, height=4)
    b.add_slope(12, 4, rise=4, steep=True)
    b.add_ground_block(16, 16, y_surface=6, height=7)
    b.add_ground_block(17, 24, y_surface=7, height=8)
    b.goal_y = 8
    return b


@test_level(34, "Steep Slope, nothing after")
def level_steep_slope_open() -> LevelBuilder:
    """The steep slope of Steep Slope Up drawn into the floor with nothing at
    its top: the floor beyond continues one row lower, under the end cap."""
    b = LevelBuilder("Steep Slope Open", "SMB1", "Ground")
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 24, y_surface=3, height=4)
    b.add_slope(12, 4, rise=4, steep=True)
    b.goal_y = 4
    return b


def _steep_slope(name: str, style: str) -> LevelBuilder:
    """A steep slope climbing five rows (columns 12..17), drawn into the
    floor, its end cap at (17, 8) over a column topped at row 7, meeting a
    column whose top is at the ramp's top row."""
    b = LevelBuilder(name, style, "Ground")
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 16, y_surface=3, height=4)
    b.add_slope(12, 4, rise=5, steep=True)
    b.add_ground_block(17, 17, y_surface=7, height=8)
    b.add_ground_block(18, 24, y_surface=8, height=9)
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
    b.add_slope(12, 4, rise=4)
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
    # Start flat ground; under the steep slope's foot (8, 4) and its next
    # column (9, 4) the floor stops a row lower, out of the slope's surface.
    b.add_ground_block(7, 7, y_surface=4, height=5)
    b.add_ground_block(8, 9, y_surface=3, height=4)
    b.add_ground_block(10, 10, y_surface=4, height=5)
    # Steep slope going up (id=88)
    b.add_slope(8, 4, rise=4, steep=True)
    # Slight slope going up (id=87)
    b.add_slope(13, 7, rise=4)
    # End ground near goal
    b.add_ground_fill(21, 23, 10)
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
       5): the first cut had it two rows lower and the enemy stopped at
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
    b.add_slope(13, 11, rise=2, descending=True)
    b.add_slope(15, 7, rise=5, steep=True, descending=True)
    b.add_ground_block(21, 26, y_surface=5, height=6)
    # B: the slope box (rows 4-5) and row 3 stay empty; floor at row 2.
    for x in range(27, 31):
        for y in range(0, 3):
            b.add_ground_fill(x, x, y)
    b.add_slope(27, 4, rise=2, descending=True)
    b.add_ground_block(31, 38, y_surface=4, height=5)
    # C: rising steep 4x3 at (39,4): the line runs (40,5)->(42,7), column 39
    # is its ledge at 5, the plateau at 7.
    for x, top in [(39, 3), (40, 3), (41, 4), (42, 5)]:
        for y in range(0, top + 1):
            b.add_ground_fill(x, x, y)
    b.add_slope(39, 4, rise=3, steep=True)
    b.add_ground_block(43, 48, y_surface=6, height=7)
    # D: rising slight 4x2 at (49,6): column 49 is its ledge at 7 (the
    # plateau height), the line runs (50,7)->(52,8), the goal ground at 8.
    for x, top in [(49, 5), (50, 5), (51, 5), (52, 6)]:
        for y in range(0, top + 1):
            b.add_ground_fill(x, x, y)
    b.add_slope(49, 6, rise=2)
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
    b.ground_tiles.append((23, 6))
    b.objects.append({'id': OBJ_SPIKE_BALL, 'x': 23, 'y': 9, 'width': 1, 'height': 1,
                      'flags': 0x06000044, '_half_tile_offset': True})
    return b


@test_level(67, "Switch Gallery")
def level_switch_gallery() -> LevelBuilder:
    """The blocks a switch flips, one of each look in a row, for reading their
    in-game sprites: dotted-line block (100) plain and alt, P-block (79) plain
    and alt, ON/OFF block (99) plain and alt. `alt` is flag 0x4 in the record,
    the editor's second form. Nothing moves, so a play screenshot shows each
    block in its initial look.
    """
    b = LevelBuilder("Switch Gallery", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    for x, oid, flags in [(9, 100, 0x06000040), (11, 100, 0x06000044), (13, 79, 0x06000040),
                          (15, 79, 0x06000044), (17, 99, 0x06000040), (19, 99, 0x06000044)]:
        b.objects.append({'id': oid, 'x': x, 'y': 6, 'width': 1, 'height': 1, 'flags': flags,
                          '_half_tile_offset': True})
    return b


@test_level(68, "Hidden Block Row")
def level_hidden_block_row() -> LevelBuilder:
    """A row of hidden blocks (29) two tiles above the floor at columns 7..12,
    for reading the spent block's sprite after the hit; a question block (5)
    at column 15 for the same spent look from the other block. The player
    spawns at x 72 (column 4.5), left of the row: walk under a block's centre
    (column * 16 + 8) before jumping.
    """
    b = LevelBuilder("Hidden Block Row", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    for x in range(7, 13):
        b.objects.append({'id': 29, 'x': x, 'y': 7, 'width': 1, 'height': 1, 'flags': 0x06000040,
                          '_half_tile_offset': True})
    b.objects.append({'id': 5, 'x': 15, 'y': 7, 'width': 1, 'height': 1, 'flags': 0x06000040,
                      '_half_tile_offset': True})
    return b


@test_level(71, "Coin Blocks")
def level_coin_blocks() -> LevelBuilder:
    """Blocks with and without a coin inside, one per column with a free
    column between, so a jump under a block's centre (column * 16 + 8) hits
    only that block: an empty hidden block (29) at column 7, a hidden block
    holding a coin at 9, an empty question block (5) at 12, a question block
    holding a coin at 15. A block's contents are its child id (the record's
    `cid`, here OBJ_COIN = 8), as the editor stores a coin dropped on it.
    The player spawns at x 72.
    """
    b = LevelBuilder("Coin Blocks", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    for x, block, contents in ((7, 29, -1), (9, 29, OBJ_COIN), (12, OBJ_QUESTION, -1), (15, OBJ_QUESTION, OBJ_COIN)):
        b.objects.append({'id': block, 'x': x, 'y': 7, 'width': 1, 'height': 1, 'flags': 0x06000040,
                          'contents': contents, '_half_tile_offset': True})
    return b


@test_level(72, "Enemy Walk")
def level_enemy_walk() -> LevelBuilder:
    """Generic enemies walking, for the enemy oracle: a Goomba (0) on the
    ground between two walls of hard blocks two high (columns 9 and 19), so
    it turns at each; a red Koopa (1 with the alt flag 0x4) alone on a
    four-block ledge (columns 15-18, row 8), which turns at the ledge's ends;
    a green Koopa (1) on a ledge right of it (columns 21-24, row 8), which
    walks off, lands right of the column-19 wall, turns there and walks off
    the ground's end at column 30. Everything is inside the opening view, so
    all of them spawn at load; the player (x 72) is fenced off by the first
    wall. The `enemywalk` preset records them every frame.
    """
    b = LevelBuilder("Enemy Walk", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    for col in (9, 19):
        b.add_platform(col, 5, 1)
        b.add_platform(col, 6, 1)
    b.add_platform(15, 8, 4)
    b.add_platform(21, 8, 4)
    b.add_actor(OBJ_GOOMBA, 13, 5)
    b.add_actor(1, 17, 9, flags=0x06000040 | 0x4)
    b.add_actor(1, 23, 9)
    return b


@test_level(81, "Hot Gallery")
def level_hot_gallery() -> LevelBuilder:
    """What a spike ball does to a block from each side, small and big, for
    the per-face hit words (sub_7101078AB0 builds them from actor+0x520; the
    block dispatcher sub_710138CEC0 reads them). Nothing needs input.

    Spike balls (74, 0x06000044) set down on flat ground roll LEFT (first
    run, 2026-09-30: every ball, belt or no belt), so each target sits left
    of its ball, and a hard-block fence at column 7 keeps them off the
    player (x 72), who a ball otherwise kills 105 frames in.
      9     question block, small ball from 10 (on a belt 10-12)
      14    brick, small ball from 15 (belt 15-17)
      21    spring, big ball, hidden blocks at row 11, 17-21: a big ball on
            a small spring does not bounce, it rolls off; a big spring
            (0x4000, 2x2 at 20,6) got the course deleted as corrupt
      25    ON/OFF switch, a Goomba at 26 boxed in by a hard block at 27, so
            it meets the switch whichever way it starts (it started right in
            one run and left in another); a Goomba carries no hit bits
    Nothing right of about column 27 spawns at load (2026-09-30), so all
    of it sits left of that. Above the view, as placeholders: a 3-wide lift
    at row 18 (centre 16, shuttles left 3 tiles) with a small ball on it and
    a question block at column 13, row 19 in its path.
    """
    b = LevelBuilder("Hot Gallery", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 37, y_surface=4, height=5)
    b.goal_y = 5

    def obj(oid, x, y, flags=0x06000040, w=1, h=1):
        b.objects.append({'id': oid, 'x': x, 'y': y, 'width': w, 'height': h,
                          'flags': flags, '_half_tile_offset': True})

    def belt(x):
        obj(53, x, 5, flags=0x06000048, w=3)

    def ball(x, y, big=False):
        if big:
            obj(OBJ_SPIKE_BALL, x, y, flags=0x06000044 | 0x4000, w=2, h=2)
        else:
            obj(OBJ_SPIKE_BALL, x, y, flags=0x06000044)

    for row in (5, 6, 7):
        obj(OBJ_HARD_BLOCK, 7, row)
    obj(OBJ_QUESTION, 9, 6);  belt(10); ball(10, 7)
    obj(OBJ_BLOCK, 14, 6);    belt(15); ball(15, 7)
    obj(10, 21, 5); ball(21, 8, big=True)
    for x in range(17, 22):
        obj(29, x, 11)
    obj(99, 25, 5)
    b.add_actor(OBJ_GOOMBA, 26, 5)
    obj(OBJ_HARD_BLOCK, 27, 5)

    # Above the view (top row 13.5): these spawn as placeholders at load.
    obj(OBJ_LIFT, 16, 18, w=3)
    ball(16, 19)
    obj(OBJ_QUESTION, 13, 19)
    return b


def _stomp_pit(name: str, enemy: int, flags: int = 0x06000040) -> LevelBuilder:
    """A stomp on a walking enemy, for the stomp oracle, with one held
    button. The course ground is three rows under the start area (surface
    row 1 against the start's 5), so the player walks off the start ledge at
    x 112, lands on a two-high hard-block post at column 7 and walks off it
    into a one-tile pit (column 8) walled by another post at 9, onto the
    enemy boxed in there. The one-tile pit matters: an enemy starts walking
    either way (it varied between runs), and in the first two-tile version
    the Koopa sometimes dodged. Record with probe preset 'stomp' and
    `record_slot.py --input RIGHT:1500`.
    """
    b = LevelBuilder(name, "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=1, height=1)
    b.goal_y = 1
    for col in (7, 9):
        for row in (2, 3):
            b.objects.append({'id': OBJ_HARD_BLOCK, 'x': col, 'y': row, 'width': 1, 'height': 1,
                              'flags': 0x06000040, '_half_tile_offset': True})
    b.add_actor(enemy, 8, 2, flags=flags)
    return b


@test_level(74, "Stomp Pit")
def level_stomp_pit() -> LevelBuilder:
    return _stomp_pit("Stomp Pit", OBJ_GOOMBA)


@test_level(75, "Stomp Pit Koopa")
def level_stomp_pit_koopa() -> LevelBuilder:
    return _stomp_pit("Stomp Pit Koopa", 1)


@test_level(78, "Stomp Pit Spiny")
def level_stomp_pit_spiny() -> LevelBuilder:
    return _stomp_pit("Stomp Pit Spiny", 25)


@test_level(79, "Stomp Pit Buzzy")
def level_stomp_pit_buzzy() -> LevelBuilder:
    return _stomp_pit("Stomp Pit Buzzy", 28)


@test_level(80, "Stomp Pit Bob-omb")
def level_stomp_pit_bobomb() -> LevelBuilder:
    return _stomp_pit("Stomp Pit Bob-omb", 15)


@test_level(76, "Walk-In")
def level_walk_in() -> LevelBuilder:
    """A walking contact with an enemy, not a stomp: flat ground at the start
    area's height, a Goomba (0) at column 10 boxed in by a two-high hard-block
    post at column 12 (and the start area's ground on the left), so the player
    holding RIGHT from the start meets it head-on whichever way it walks.
    Record with the stomp preset plus hooks on the stomp test (x1: paths) to
    see what the contact classifier makes of a side contact.
    """
    b = LevelBuilder("Walk-In", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    for row in (5, 6):
        b.objects.append({'id': OBJ_HARD_BLOCK, 'x': 12, 'y': row, 'width': 1, 'height': 1,
                          'flags': 0x06000040, '_half_tile_offset': True})
    b.add_actor(OBJ_GOOMBA, 10, 5)
    return b


OBJ_SPRING = 10          # Jumpdai (smm2-decomp MapObjJumpdai, runtime type 48)
FLAG_SIDE_SPRING = 0x4  # the record's alternate bit: the sideways spring (runtime type 70)


def _spring(b: LevelBuilder, x: int, y: int, side: bool = False):
    """A spring record as Hot Gallery's (level 81) is: a sized object, width
    and height 1 (add_actor leaves them out, and the game refused the course)."""
    b.objects.append({'id': OBJ_SPRING, 'x': x, 'y': y, 'width': 1, 'height': 1,
                      'flags': 0x06000040 | (FLAG_SIDE_SPRING if side else 0), '_half_tile_offset': True})


@test_level(110, "Spring Walk")
def level_spring_walk() -> LevelBuilder:
    """One spring (record 10) in a one-tile pit at column 9, its top flush
    with the flat SMB1 ground, four tiles right of the start: walked onto
    from the start with no jump, for the launch (no button, B held from the
    landing on it, B pressed after the launch). Record with
    `player,spring` (smm2-decomp's test_spring)."""
    b = LevelBuilder("Spring Walk", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 8, y_surface=4, height=5)
    b.add_ground_block(9, 9, y_surface=3, height=4)
    b.add_ground_block(10, 30, y_surface=4, height=5)
    b.goal_y = 5
    _spring(b, 9, 4)
    return b


@test_level(111, "Side Spring")
def level_side_spring() -> LevelBuilder:
    """One sideways spring (record 10 with the alternate bit 0x4) on flat SMB1
    ground at column 10: walked into from the start and pushed against
    (smm2-decomp's test_side_spring). Record with `player,spring`."""
    b = LevelBuilder("Side Spring", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    _spring(b, 10, 5, side=True)
    return b


@test_level(112, "Side Spring Ledge")
def level_side_spring_ledge() -> LevelBuilder:
    """The sideways spring on ground two tiles below the start area (surface
    2, from column 7), at column 10: the player walks off the start ledge and
    into the spring, whose push slides him back to the ledge's face, where
    he stops (recorded 2026-10-21: side-spring-push-ledge). Not the far-side
    wall case (a player already against a wall when pushed): with the spring
    one tile from the face he fell onto its top instead. Record with
    `player,spring`."""
    b = LevelBuilder("Side Spring Ledge", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=2, height=3)
    b.goal_y = 3
    _spring(b, 10, 3, side=True)
    return b


@test_level(113, "Fire Throw")
def level_fire_throw() -> LevelBuilder:
    """A Fire Flower at column 9 on flat SMB1 ground, then a long run: small
    Mario takes it and throws standing, running and in the air (the Fire
    state, 45; smm2-decomp's PlayerStateFire.cpp). Record with `player`."""
    b = LevelBuilder("Fire Throw", "SMB1", "Ground")
    b.width = 64
    b.add_ground_block(7, 50, y_surface=4, height=5)
    b.add_actor(OBJ_FIRE_FLOWER, 9, 5)
    b.goal_y = 5
    return b


@test_level(133, "Fire Bounce")
def level_fire_bounce() -> LevelBuilder:
    """Fire Throw's flower, then ground for the fireball to bounce on: flat
    to column 15, a rising slight slope (4x2 at column 16, laid as Slope
    Walk's D: its box on the ground's top row, a staircase under it), a
    plateau one row higher from column 20, and a wall of hard blocks four
    high at column 34 on it. Thrown from the flower, a fireball bounces
    along the flat, up the slope and across the plateau into the wall;
    thrown on the plateau, it meets the wall a few tiles out."""
    b = LevelBuilder("Fire Bounce", "SMB1", "Ground")
    b.width = 64
    b.add_ground_block(7, 15, y_surface=4, height=5)
    for x, top in [(16, 3), (17, 3), (18, 3), (19, 4)]:
        for y in range(0, top + 1):
            b.add_ground_fill(x, x, y)
    b.add_slope(16, 4, rise=2)
    b.add_ground_block(20, 50, y_surface=5, height=6)
    b.add_actor(OBJ_FIRE_FLOWER, 9, 5)
    for row in range(6, 10):
        b.objects.append({'id': OBJ_HARD_BLOCK, 'x': 34, 'y': row, 'width': 1, 'height': 1,
                          '_half_tile_offset': True})
    b.goal_y = 6
    return b


@test_level(134, "Fire Piranha")
def level_fire_piranha() -> LevelBuilder:
    """Two fire piranhas (record 2 with the alternate bit 0x4: runtime type
    123, GameEnemyFirePakkun), for where their shots aim. One stands in a
    dip three rows deep (columns 18-22, the plant at column 20 on row 2),
    so the player passes above it on both sides; the other sits in a
    mouth-up pipe at columns 27-28 (Plant Pipe Near's pipe and in-pipe
    record), level with him."""
    b = LevelBuilder("Fire Piranha", "SMB1", "Ground")
    b.width = 64
    b.add_ground_block(7, 17, y_surface=4, height=5)
    b.add_ground_block(18, 22, y_surface=1, height=2)
    b.add_ground_block(23, 50, y_surface=4, height=5)
    b.add_actor(2, 20, 2, flags=0x06000044)
    b.objects.append({'id': 9, 'x': 27, 'y': 5, 'width': 2, 'height': 2, 'flags': 0x060400C0,
                      'lid': 1, '_half_tile_offset': True})
    b.objects.append({'id': 2, 'x': 28, 'y': 7, 'width': 1, 'height': 1, 'flags': 0x06000045,
                      'lid': 1, '_half_tile_offset': False})
    b.goal_y = 5
    return b


@test_level(114, "Fire Swim")
def level_fire_swim() -> LevelBuilder:
    """The Fire Throw course under water (SMB1 Underwater): the flower taken
    swimming, then throws in the water (FireSwim, 46). Record with
    `player`."""
    b = LevelBuilder("Fire Swim", "SMB1", "Underwater")
    b.width = 64
    b.add_ground_block(7, 50, y_surface=4, height=5)
    b.add_actor(OBJ_FIRE_FLOWER, 9, 5)
    b.goal_y = 5
    return b


@test_level(115, "Wall Hit 3DW")
def level_wall_hit_3dw() -> LevelBuilder:
    """3D World flat ground with a wall ten tiles high at columns 34..36: a
    run at full speed into it bonks him off (WallHitLand, 38, on the
    ground; WallHit, 37, jumped into it; smm2-decomp's
    PlayerStateWallHit.cpp). Record with `player`."""
    b = LevelBuilder("Wall Hit 3DW", "3DW", "Ground")
    b.width = 64
    b.add_ground_block(7, 33, y_surface=4, height=5)
    b.add_ground_block(34, 36, y_surface=14, height=15)
    b.add_ground_block(37, 50, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(77, "Enemy Zoo")
def level_enemy_zoo() -> LevelBuilder:
    """More walking enemies for the walking-enemy oracle, each boxed in its own
    three-tile run between two-high hard-block posts so it turns at walls:
    a Spiny (25) at column 9, a Buzzy Beetle (28) at 13 and a Bob-omb (15) at
    17 (posts at 8, 11, 12, 15, 16, 19); the player (x 72) is fenced off by
    the first post. Everything is in the opening view. Record with the
    `enemywalk` preset plus a hook on the wall resolver sub_7100E1EE80 (the
    owner at bg+0x188, the side / head / foot sensors behind +0x1A8..+0x1C0).
    """
    b = LevelBuilder("Enemy Zoo", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    for col in (8, 11, 12, 15, 16, 19):
        for row in (5, 6):
            b.objects.append({'id': OBJ_HARD_BLOCK, 'x': col, 'y': row, 'width': 1, 'height': 1,
                              'flags': 0x06000040, '_half_tile_offset': True})
    b.add_actor(25, 9, 5)
    b.add_actor(28, 13, 5)
    b.add_actor(15, 17, 5)
    return b


@test_level(64, "Note Pitch")
def level_note_pitch() -> LevelBuilder:
    """A height sweep of note blocks, for the pitch reading. One free-standing
    block per column from 8 to 20, each a row higher than the last (rows 5 to
    17), plus a second block at the SAME row as the first two columns further
    on, so the reading says whether x matters. Every block is inside the
    opening view, so all of them spawn at load and register their sound
    there. The `notepitch` preset reads the 5-bit slot at actor+0x914 beside
    the position, so the recording gives slot against spawn height directly.
    """
    b = LevelBuilder("Note Pitch", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    def block(x, y):
        return {'id': OBJ_NOTE_BLOCK, 'x': x, 'y': y, 'width': 1, 'height': 1, '_half_tile_offset': True}
    for i, col in enumerate(range(8, 21)):
        b.objects.append(block(col, 5 + i))
    b.objects.append(block(22, 5))    # the same row as column 8: does x matter
    b.objects.append(block(23, 6))    # and the same row as column 9
    return b


@test_level(63, "Note Ceiling")
def level_note_ceiling() -> LevelBuilder:
    """A note block's impulse thrown into a ceiling. Two columns, each a note
    block at row 6 with a Goomba on it (row 7, its box top at 128, boxed in
    by a hard block either side so it does not walk off) and a hard-block
    ceiling over it: column 11 with its underside at 144, one tile of
    headroom, and column 17 at 192, four. Jumping into each
    block from below fires it; the `placeholder` preset's enemy hook reads
    the Goomba's y and vel_y per frame, so the recording says whether the body
    keeps any of its upward speed at the ceiling and where its top comes to
    rest. The gaps differ so a stop that depends on the speed at contact
    separates from one that does not.
    """
    b = LevelBuilder("Note Ceiling", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    def block(x):
        return {'id': OBJ_NOTE_BLOCK, 'x': x, 'y': 6, 'width': 1, 'height': 1, '_half_tile_offset': True}
    def goomba(x):
        return {'id': OBJ_GOOMBA, 'x': x, 'y': 7, 'width': 1, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True}
    def hard(x, y):
        return {'id': OBJ_HARD_BLOCK, 'x': x, 'y': y, 'width': 1, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True}
    for col, ceil in ((11, 9), (17, 12)):
        b.objects.append(block(col))
        # Boxed in on the block's top: an enemy left alone strolls off a
        # one-tile block long before the player arrives.
        b.objects.append(goomba(col))
        b.objects.append(hard(col - 1, 7))
        b.objects.append(hard(col + 1, 7))
        for x in (col - 1, col, col + 1):
            b.objects.append(hard(x, ceil))
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


def _runway(name: str, style: str, theme: str = 'Ground') -> LevelBuilder:
    """A 100-tile flat runway: room for a run to full speed, a running turn and
    jumps that land at rest."""
    b = LevelBuilder(name, style, theme)
    b.width = 100
    b.add_ground_block(7, 89, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(92, "Landings NSMBU")
def level_landings_nsmbu() -> LevelBuilder:
    """Recording batch 1 (smm2-decomp tasks/todo.md 5h): an NSMBU landing at
    rest (the sim predicts 9 rows of Landing, "jumped" 8 frames), a running
    jump with run held through 0.5..1.5 in the air (the air run row's 0.06),
    a second jump's landing, and a running turn ("turned"'s length)."""
    return _runway("Landings NSMBU", "NSMBU")


@test_level(93, "Landings SMW")
def level_landings_smw() -> LevelBuilder:
    """Recording batch 1: SMW landings at rest (1 row predicted) and with a
    direction held (Landing's phase 3, 4 rows predicted), a running jump and
    a running turn."""
    return _runway("Landings SMW", "SMW")


@test_level(96, "Landings 3DW")
def level_landings_3dw() -> LevelBuilder:
    """Recording batch 2: a 3D World landing at rest (its landing animation's
    length is not known to the sim) and running ones."""
    return _runway("Landings 3DW", "3DW")


@test_level(97, "Star Runway")
def level_star_runway() -> LevelBuilder:
    """Recording batch 3: the runway with a Super Star (35) on the floor at
    tile 9 (slot 29's "Star Run" places id 29, a hidden block): does
    invincibility set +0x27D4, the speed tables' second rows?"""
    b = _runway("Star Runway", "SMB1")
    b.add_actor(OBJ_SUPER_STAR, 9, 5)
    # A one-row tunnel (a ceiling at row 6, tiles 8..30): the star cannot
    # bounce over a small Mario running at it.
    b.add_ground_block(8, 30, y_surface=6, height=1)
    return b


@test_level(98, "Ice Runway")
def level_ice_runway() -> LevelBuilder:
    """Recording batch 3: the floor is ice blocks from tile 13 to 70 (ground
    before and after): the ground speed's slippery tables."""
    b = LevelBuilder("Ice Runway", "SMB1", "Ground")
    b.width = 100
    b.add_ground_block(7, 12, y_surface=4, height=5)
    b.add_ice(13, 70, 4)
    b.add_ground_block(71, 89, y_surface=4, height=5)
    b.goal_y = 5
    return b


def _ice_runway(name: str, style: str, theme: str = 'Ground', night: bool = False) -> LevelBuilder:
    b = LevelBuilder(name, style, theme)
    b.width = 100
    b.add_ground_block(7, 12, y_surface=4, height=5)
    b.add_ice(13, 70, 4)
    b.add_ground_block(71, 89, y_surface=4, height=5)
    b.goal_y = 5
    if night:
        b.area_flag = 2
    return b


@test_level(106, "Slide Ledge SMB3")
def level_slide_ledge_smb3() -> LevelBuilder:
    """Slip in the air (smm2-decomp, Slip's execute off the ground): in SMB3, a
    gentle ramp up to the right (object 87 at 12,4, as Gentle Slope's), a
    plateau at tiles 20..24 (top row 7), a gentle ramp down to the right
    (25,4, flag 0x100000), a floor at tile 33, a pit at 34..35 and a lower
    floor from 36 (top row 1). A slide down the second ramp runs on over the
    floor and off its edge."""
    b = LevelBuilder("Slide Ledge 3", "SMB3", "Ground")
    b.width = 100
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 19, y_surface=3, height=4)
    b.add_slope(12, 4, rise=4)
    b.add_ground_block(20, 24, y_surface=7, height=8)
    b.add_ground_block(25, 32, y_surface=3, height=4)
    b.add_slope(25, 4, rise=4, descending=True)
    b.add_ground_block(33, 33, y_surface=4, height=5)
    b.add_ground_block(36, 89, y_surface=1, height=2)
    b.goal_y = 2
    return b


def level_theme_probe(theme: str, night: bool) -> LevelBuilder:
    """A short SMB1 runway in any theme, by day or at night (slot 107 by
    hand, one theme at a time): the ground's kind word (+0x22E4) standing on
    it carries the theme's sound bits in its top five bits (smm2-decomp
    BlockColliderKind.cpp, the area's sound table by the collider's name)."""
    b = _runway(f"Theme {theme} {'N' if night else 'D'}", "SMB1", theme)
    if night:
        b.area_flag = 2
    return b


@test_level(103, "Ice Runway NSMBU")
def level_ice_runway_nsmbu() -> LevelBuilder:
    """Recording batch 4 (smm2-decomp Turn): Ice Runway in NSMBU, a running
    turn on the ice ("ice_turned"'s length in NSMBU)."""
    return _ice_runway("Ice Runway NSMBU", "NSMBU")


@test_level(104, "Ice Runway 3DW")
def level_ice_runway_3dw() -> LevelBuilder:
    """Recording batch 4: Ice Runway in 3D World ("ice_turned" in 3DW)."""
    return _ice_runway("Ice Runway 3DW", "3DW")


@test_level(105, "Snow Night Ice NSMBU")
def level_snow_night_ice_nsmbu() -> LevelBuilder:
    """Recording batch 4: ice blocks in the Snow theme at night (NSMBU): the
    turn's rate times 0.8 on ice when the night's ground is slippery too."""
    return _ice_runway("Snow Night Ice NSMBU", "NSMBU", "Snow", night=True)


def _night(name: str, theme: str) -> LevelBuilder:
    b = _runway(name, "SMB1", theme)
    b.area_flag = 2
    return b


@test_level(99, "Snow Night")
def level_snow_night() -> LevelBuilder:
    """Recording batch 3: the Snow theme at night, whose ground is slippery
    (the ground speed's area kind 6 with +0x2C 1)."""
    return _night("Snow Night", "Snow")


@test_level(100, "Underground Night")
def level_underground_night() -> LevelBuilder:
    """Recording batch 3: the Underground theme at night, where the pad
    refresh negates the stick's y (PlayerPad.cpp: area +0x28 and +0x2C 1)."""
    return _night("Underground Night", "Underground")


@test_level(101, "Desert Night")
def level_desert_night() -> LevelBuilder:
    """Recording batch 3: the Desert theme at night, its wind (the move's
    area push, [area +0x48] +0xC)."""
    return _night("Desert Night", "Desert")


@test_level(102, "Wall Ledge NSMBU")
def level_wall_ledge_nsmbu() -> LevelBuilder:
    """Recording batch 3: NSMBU, a raised floor at tiles 15..25 (3 rows up) to
    jump onto, ground-pound on and walk off its right edge, then a wall 12
    rows high at tiles 40..41 to slide down and jump off."""
    b = _runway("Wall Ledge NSMBU", "NSMBU")
    b.add_ground_block(15, 25, y_surface=7, height=3)
    b.add_ground_block(40, 41, y_surface=16, height=12)
    return b


@test_level(94, "Sky Night")
def level_sky_night() -> LevelBuilder:
    """Recording batch 1: the Sky theme at night (area flag bit 1) in SMB1:
    the move's night sky gives a fifth of the gravity and half the floor."""
    b = _runway("Sky Night", "SMB1", "Sky")
    b.area_flag = 2
    return b


@test_level(95, "Crouch Jumps")
def level_crouch_jumps() -> LevelBuilder:
    """Recording batch 1: big Mario's crouch jumps in SMB1, one in the open
    with down released while rising, one under a block row (tiles 30..34,
    row 8: three free rows over the ground), where the head room keeps him
    crouched. A mushroom at tile 8 makes him big."""
    b = _runway("Crouch Jumps", "SMB1")
    b.add_actor(OBJ_MUSHROOM, 8, 5)
    b.add_ground_block(30, 34, y_surface=8, height=1)
    return b


@test_level(9, "Empty")
def level_empty() -> LevelBuilder:
    """Minimal empty level for custom tests - NO ground placed."""
    b = LevelBuilder("Empty", "SMB1", "Ground")
    # Don't place any ground - start/goal areas are auto-generated
    b.start_y = 5
    b.goal_y = 5
    return b


@test_level(69, "Swim Pool")
def level_swim_pool() -> LevelBuilder:
    """A forest pool for the swim reads (docs/re-notes/swim.md): still water
    with its surface at row 5 (y 92) over a flat floor, and two ledges to
    climb out onto, their tops 4 and 20 units above the surface. The player
    starts on the floor under the water; strokes, the rise cap and the launch
    out are what the recording is for."""
    b = LevelBuilder("Swim Pool", "SMB1", "Forest")
    b.liquid = (5, 0, 0, 5)
    b.add_ground_block(7, 24, y_surface=1, height=1)
    b.add_ground_block(13, 15, y_surface=6, height=5)    # top 96: 4 above the water
    b.add_ground_block(19, 23, y_surface=7, height=6)    # top 112: 20 above it
    b.goal_y = 1
    return b


@test_level(70, "Belt Jump")
def level_belt_jump() -> LevelBuilder:
    """Conveyors on the floor to jump off: what the belt's carry does to a
    jump's speed. Flat SMB1 ground, an 8-wide fast belt running right from
    tile 10 and a 7-wide normal one right after it, room to land past them.

    Both belts are object 53; flag bit 0x40000 makes it the fast one (the
    Lost Woods' flat belts are all 53, 0x6040048 fast and 0x6000048 normal).
    Object 94 is the sloped belt (its records are 3x2, 4x3, 7x6 boxes) and a
    flat 94 is a course Coursebot deletes, 2026-09-15."""
    b = LevelBuilder("Belt Jump", "SMB1", "Ground")
    # A wider area keeps the goal zone clear of the second belt.
    b.width = 48
    # The floor is row 1 (top 32); the belts take that row from tile 10 to
    # 24 so the player walks straight onto them (a belt a row higher is a
    # wall), with ground on both sides.
    b.add_ground_block(7, 9, y_surface=1, height=1)
    b.add_ground_block(25, 34, y_surface=1, height=1)
    b.objects.append({'id': 53, 'x': 10, 'y': 1, 'width': 8, 'height': 1,
                      'flags': 0x06040048, '_half_tile_offset': True})
    b.objects.append({'id': 53, 'x': 18, 'y': 1, 'width': 7, 'height': 1,
                      'flags': 0x06000048, '_half_tile_offset': True})
    b.goal_y = 1
    return b


@test_level(73, "Belt Enemies")
def level_belt_enemies() -> LevelBuilder:
    """Goombas and Koopas walking on belts: what a belt's carry does to an
    enemy, and when the game counts it as standing. Three floor belts
    between hard-block walls two high, so every enemy turns at the walls and
    walks both with and against its belt: a normal belt with the flags Belt
    Jump uses (0x06000048), the same without bit 0x8 (0x06000040; the facing
    bit, so it should run the other way) and a fast one (0x06040048). Each
    holds a Goomba (0) and a green Koopa (1). The first belt is inside the
    opening view; the player (x 72) is fenced off by the first wall and walks
    on to bring the others in. The `enemywalk` preset records them every
    frame with their bg-check flags."""
    b = LevelBuilder("Belt Enemies", "SMB1", "Ground")
    b.width = 52
    b.add_ground_block(7, 9, y_surface=1, height=1)
    b.add_ground_block(38, 41, y_surface=1, height=1)
    belts = ((11, 0x06000048), (20, 0x06000040), (29, 0x06040048))
    for left, flags in belts:
        b.objects.append({'id': 53, 'x': left, 'y': 1, 'width': 8, 'height': 1,
                          'flags': flags, '_half_tile_offset': True})
        b.add_actor(OBJ_GOOMBA, left + 2, 2)
        b.add_actor(1, left + 5, 2)
    for col in (10, 19, 28, 37):
        b.add_ground_block(col, col, y_surface=1, height=1)
        b.add_platform(col, 2, 1)
        b.add_platform(col, 3, 1)
    b.goal_y = 1
    return b


@test_level(65, "Stack Drop")
def level_stack_drop() -> LevelBuilder:
    """How far below the camera a stack of enemies stays loaded, in a vertical
    area.

    A stack is held by its own container (`game::GameEnemyTowerManager`), and
    its spawn/despawn is believed to follow its members rather than its own
    position. In a vertical area that appears to stop somewhere around seven
    screens below the camera -- a rough figure from play, measured from the
    camera, and the one load distance the community's table does not cover
    (docs/re-notes/globality.md in smm2-decomp).

    The rig: two Bowsers stacked on a note block near the top of a tall
    vertical subworld, nothing else in the column, and a floor far below. The
    player takes the pipe down, is spat out beside the stack with nothing
    underneath, and falls the length of the column; the bosses keep landing on
    the block so it keeps sounding, and the frame the sound stops is the frame
    the stack unloaded. Read the distance off the camera, not off the player.

    A vertical area is always the SUBWORLD -- it has no goal of its own, the
    overworld carries it -- so the overworld here is a short strip with the
    goal and the entry pipe.

    **Pipes, not doors.** A door pairs 2k with 2k+1 inside one area; crossing
    between the overworld and the subworld is what a pipe is for. The Lost
    Woods does exactly this (its doors pair within the subworld, its pipe
    link 1 crosses to the overworld), and both flag words here are copied off
    that pair: mouth up to enter, mouth right to be spat out. An unlinked
    pipe (link 0) leads nowhere, so the link is 1 on both sides.

    Autoscroll is left off (`sub_autoscroll = 0`). A vertical area scrolls
    UPWARD when it is on, which carries the spawn window with it and would
    confound a measurement of how far *behind* the camera a stack survives --
    turn it on deliberately to measure the interaction, not by default.

    Each Bowser is two tiles tall (spawn_rects.csv type 62: off_y 16,
    half_h 16), so they stack at +1 and +3 above the block.
    """
    b = LevelBuilder("Stack Drop", "SMB1", "Ground")

    # Overworld: the goal, and the pipe down. A mouth-up pipe at (10, 5)
    # stands two tiles out of the ground; the player walks on top and presses
    # down. Kept well clear of the goal area.
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    b.objects.append({'id': OBJ_PIPE, 'x': 10, 'y': 5, 'width': 2, 'height': 2,
                      'flags': PIPE_UP_LINK1})

    # Subworld: the column. Lost Woods' own subworld size (48 x 168 tiles),
    # so the dimensions are known-good rather than invented.
    b.sub_vertical = True
    b.sub_width = 48
    b.sub_height = 168
    col = 12
    top = b.sub_height - 8
    for x in range(col - 4, col + 5):
        b.sub_ground_tiles.append((x, 4))          # the floor, far below
    # The exit, mouth right, LEVEL with the stack and over open air: the player
    # is spat out sideways with the stack beside them, so it is inside the
    # view on arrival and spawns, then recedes above as they fall. Put the
    # exit below the stack instead and the bosses start off-screen, which
    # measures when they first spawn rather than when they unload.
    b.sub_objects.append({'id': OBJ_PIPE, 'x': col + 4, 'y': top + 4,
                          'width': 2, 'height': 2, 'flags': PIPE_RIGHT_LINK1})
    for dx in (-1, 0, 1):                                        # the block's perch
        b.sub_objects.append({'id': OBJ_HARD_BLOCK, 'x': col + dx, 'y': top,
                              'width': 1, 'height': 1, '_half_tile_offset': True})
    b.sub_objects.append({'id': OBJ_NOTE_BLOCK, 'x': col, 'y': top + 1,
                          'flags': 0x06000040})
    for dy in (2, 4):                                            # the two Bowsers
        b.sub_objects.append({'id': 62, 'x': col, 'y': top + dy,
                              'flags': 0x06000040, '_half_tile_offset': True})
    return b


@test_level(66, "Detached Block")
def level_detached_block() -> LevelBuilder:
    """The "broken track" glitch: a music block whose rail is not under it.

    The undo-dog glitch leaves, in the file, a rider that still carries the
    on-track flag and a link id, while the piece it names is gone -- so the
    lid resolves to some unrelated record elsewhere and nothing holds the
    block (smm2-decomp docs/re-notes/track-linkage.md). The Lost Woods has one
    at tile 111.5, 15.5 whose lid points at a piece a hundred tiles away, and
    Coursebot accepts the course, so the shape is legal to save.

    In the real game such a block **launches upward, away from the track it
    spawns on** rather than sitting where its record puts it. That launch is
    the thing this level exists to measure: nothing we hold records it, since
    the overworld recording stops well short of Lost Woods' corner.

    Two blocks, so one run gives both sides:
      A (col 11) a normal block on its own capped piece -- the control.
      B (col 20) the same record, on-track and linked to A's piece, but placed
                 nine tiles away over open ground with no rail under it.

    Record with the `rail` preset and compare B's first frames against A's.
    """
    b = LevelBuilder("Detached Block", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    # A: a two-piece capped rail with a block riding it
    first = b.add_track(10, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, 0x0070))
    b.add_track(12, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x0071, 0x0104))
    b.add_note_block_on_track(first, travel_left=False)
    # B: the detached one. Same flags as a rider, linked to A's piece, but its
    # own position is bare ground -- the state the glitch leaves behind.
    b.objects.append({'id': OBJ_NOTE_BLOCK, 'x': 20, 'y': 8,
                      'flags': 0x06000040 | FLAG_ON_TRACK, 'lid': first,
                      '_half_tile_offset': True})
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


@test_level(84, "Fire Flower")
def level_fire_flower() -> LevelBuilder:
    """Big Flat's floor with a Fire Flower where its mushroom stands: small
    Mario runs into it and turns Fire (the power change from small)."""
    b = LevelBuilder("Fire Flower", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_actor(OBJ_FIRE_FLOWER, 9, 5)
    b.goal_y = 5
    return b


@test_level(85, "Mushroom Then Flower")
def level_mushroom_then_flower() -> LevelBuilder:
    """Big Flat's mushroom, then a Fire Flower at tile 18: one run takes
    small to Super, then Super to Fire."""
    b = LevelBuilder("Mushroom Then Flower", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_actor(OBJ_MUSHROOM, 9, 5)
    b.add_actor(OBJ_FIRE_FLOWER, 18, 5)
    b.goal_y = 5
    return b


@test_level(86, "Bump Wall")
def level_bump_wall() -> LevelBuilder:
    """A Goomba walks left along a ledge (rows 7..8, top row 8) into a brick
    at its own height (column 12, row 9). Small Mario stands under the brick
    and strikes it from below, so the brick bounds while the Goomba meets
    it: whether the Goomba turns at the bounding brick's face."""
    b = LevelBuilder("Bump Wall", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_ground_block(13, 22, y_surface=8, height=2)
    b.add_actor(OBJ_BLOCK, 12, 9)
    b.add_actor(OBJ_GOOMBA, 20, 9)
    b.goal_y = 5
    return b

@test_level(87, "Star Munchers")
def level_star_munchers() -> LevelBuilder:
    """A Super Star at tile 9 and two Munchers at tiles 18 and 19 on Big
    Flat's floor: whether a player with the star stops at a Muncher's face,
    stands on its top, or passes through it."""
    b = LevelBuilder("Star Munchers", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_actor(OBJ_SUPER_STAR, 9, 5)
    b.add_actor(OBJ_MUNCHER, 18, 5)
    b.add_actor(OBJ_MUNCHER, 19, 5)
    b.goal_y = 5
    return b

@test_level(88, "Switch Timing")
def level_switch_timing() -> LevelBuilder:
    """The switches' timing: an ON/OFF switch two tiles over the floor at
    column 9 for a standing jump to strike (twice: the toggle, its cooldown),
    a blue dotted-line block beside it at column 11 (its solidity across the
    flip), and a P-switch on the floor at column 15 to land on (the request,
    the press, the 540-frame window)."""
    b = LevelBuilder("Switch Timing", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_actor(OBJ_ON_OFF_SWITCH, 9, 7)
    b.add_actor(OBJ_DOTTED_LINE, 11, 7)
    b.add_actor(OBJ_P_SWITCH, 15, 5)
    b.goal_y = 5
    return b

@test_level(82, "Winged Goomba")
def level_winged_goomba() -> LevelBuilder:
    """One winged Goomba on flat ground, far from the start, for the wing
    component's hop (docs/re-notes/enemy-containers.md, "Wing 1"): the
    rest, the turn toward the player and the flap speed, with no input."""
    b = LevelBuilder("Winged Goomba", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    b.add_actor(OBJ_GOOMBA, 20, 5, flags=0x06000040 | FLAG_WINGS)
    return b


@test_level(89, "Winged Koopas")
def level_winged_koopas() -> LevelBuilder:
    """A green Koopa with wings and a red Koopa with wings on flat ground,
    for the Koopa's two Wing handlers (docs/re-notes/enemy-containers.md,
    "Wing 1"): the green one hops along the ground past two hard-block
    walls two high (columns 9 and 19), which its hop clears (recorded
    2026-10-13: it lands on each wall's top and hops on); the red one flies
    up and down about its start height right of the second wall, facing the
    player, but at column 25 it sits outside the opening view. The player
    (x 72) is fenced off by the first wall; no input. The `enemywalk` preset
    records them every frame."""
    b = LevelBuilder("Winged Koopas", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    for col in (9, 19):
        b.add_platform(col, 5, 1)
        b.add_platform(col, 6, 1)
    b.add_actor(1, 14, 5, flags=0x06000040 | FLAG_WINGS)
    b.add_actor(1, 25, 5, flags=0x06000040 | FLAG_WINGS | 0x4)
    return b


@test_level(90, "Winged Koopas Walls")
def level_winged_koopas_walls() -> LevelBuilder:
    """Winged Koopas with walls the hop cannot clear: hard-block walls three
    high at columns 9 and 19, the green Koopa with wings between them (it
    turns at each), the red Koopa with wings at column 22, inside the
    opening view, flying up and down and facing the player. The player (x
    72) is fenced off by the first wall; no input. The `enemywalk` preset
    records them every frame."""
    b = LevelBuilder("Winged Koopas Walls", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    for col in (9, 19):
        for row in (5, 6, 7):
            b.add_platform(col, row, 1)
    b.add_actor(1, 14, 5, flags=0x06000040 | FLAG_WINGS)
    b.add_actor(1, 22, 5, flags=0x06000040 | FLAG_WINGS | 0x4)
    return b


@test_level(91, "Shell Note")
def level_shell_note() -> LevelBuilder:
    """A green Koopa walking left toward the player and a note block on the
    floor at column 20: the player stomps the Koopa, backs off and kicks the
    shell right into the block's side, for a note block hit from the side
    (BoundUp) and what the shell does after."""
    b = LevelBuilder("Shell Note", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    b.add_actor(1, 12, 5)
    b.add_note_block(20, 5)
    return b


@test_level(83, "Claw Goomba")
def level_claw_goomba() -> LevelBuilder:
    """A swinging claw a tile above the ground line and a Goomba walking
    into it from the right, for the claw's grab, carry and release
    (docs/re-notes/enemy-containers.md, "Crane 16"), with no input."""
    b = LevelBuilder("Claw Goomba", "SMB1", "Ground")
    b.width = 48
    b.add_ground_block(7, 30, y_surface=4, height=5)
    b.goal_y = 5
    b.add_actor(OBJ_GOOMBA, 22, 5)
    b.add_actor(105, 18, 6)   # SwingingClaw (course object 105)
    return b


def level_json(builder_func):
    """The level as parse_course.py --json prints it, from the generator's own bytes."""
    import json
    import tempfile
    import parse_course
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'course_data_000.bcd')
        with open(path, 'wb') as f:
            f.write(encrypt_course(builder_func().build()))
        course = parse_course.parse_course(parse_course.decrypt_course(path))
    return json.dumps(course, indent=2, default=str) + '\n'

@test_level(107, "Water Jump")
def level_water_jump() -> LevelBuilder:
    """Into the water at speed: a dry ledge four rows over the surface to
    walk or run along, then a pool to jump into. What the swim's enter does
    with a speed past 1.125 and a fall past -1.5 (sub_71015E8AC0), and the
    air's last frames above the surface. SMB1 Forest, still water with its
    surface at row 5 (y 92), the ledge's top at row 9 (y 144), the pool's
    floor at row 1."""
    b = LevelBuilder("Water Jump", "SMB1", "Forest")
    b.width = 60
    b.start_y = 9
    b.liquid = (5, 0, 0, 5)
    b.add_ground_block(7, 16, y_surface=8, height=9)   # x 0..6 is the generated start area; feet at row 9
    b.add_ground_block(17, b.width - 11, y_surface=1, height=1)
    b.goal_y = 1
    return b

@test_level(128, "Vertical Entry Riders")
def level_vertical_entry_riders() -> LevelBuilder:
    """Note blocks on tracks above a pipe exit in a vertical subworld.

    A community melody loop ('melody only2', smm2-decomp
    marble-melody-loop_course_045.bcd) has its note blocks in a vertical
    subworld 48 x 168 tiles, reached by a pipe whose exit is at (312, 2376).
    On the first frame recorded there the game already runs riders up to
    ~330 units above the player, mid-path; the sim never spawns the ones
    above y 2528. This keeps that geometry and nothing else: Stack Drop's
    crossing (a mouth-up pipe on the overworld, link 1) into the column, the
    exit mouth right at the same place with a floor under it, and a note
    block on a lone horizontal piece every 3 rows from row 150 to 165, by the
    exit (column 8) and across the column (column 36), so a recording of the
    crossing shows which riders the game runs, and from which frame.
    """
    b = LevelBuilder("Vertical Entry Riders", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    b.objects.append({'id': OBJ_PIPE, 'x': 10, 'y': 5, 'width': 2, 'height': 2,
                      'flags': PIPE_UP_LINK1})

    b.sub_vertical = True
    b.sub_width = 48
    b.sub_height = 168
    b.sub_objects.append({'id': OBJ_PIPE, 'x': 19, 'y': 148, 'width': 2, 'height': 2,
                          'flags': PIPE_RIGHT_LINK1})
    for x in range(14, 34):
        b.sub_ground_tiles.append((x, 144))            # the floor under the exit
    for col in (8, 36):
        for row in range(150, 166, 3):
            i = len(b.sub_tracks)
            b.sub_tracks.append({'x': col - 1, 'y': row - 1, 'type': TRACK_SHAPE_HORIZONTAL,
                                 'lid': i + 1, 'has_object': True, 'tail': TRACK_END_FREE_H})
            b.sub_objects.append({'id': OBJ_NOTE_BLOCK, 'x': col, 'y': row,
                                  'flags': 0x06000040 | FLAG_ON_TRACK, 'lid': i,
                                  '_half_tile_offset': True})
    return b


@test_level(129, "Vertical Entry Stars")
def level_vertical_entry_stars() -> LevelBuilder:
    """Vertical Entry Riders with a Super Star on the three high blocks by the exit.

    The melody loop's 24 high note blocks each carry a Super Star one tile
    above them, and those blocks are running when the player comes out of
    the pipe although they are above the activation box. Here the blocks at
    rows 159, 162 and 165 by the exit get a star (at rows 160, 163, 166);
    the column across stays without, as the control. Recorded in smm2recomp
    with the same pad as level 128: the game runs five riders from the first
    frame after landing, the three in the box and the starred ones at rows
    159 and 162; the one at 165, whose star is higher, stays unloaded.
    """
    b = level_vertical_entry_riders()
    b.name = "Vertical Entry Stars"
    for row in (159, 162, 165):
        b.sub_objects.append({'id': OBJ_SUPER_STAR, 'x': 8, 'y': row + 1,
                              'flags': 0x06000040, '_half_tile_offset': True})
    return b


def pipe_flags(link: int, mouth: int) -> int:
    """A warp pipe's flag word: Lost Woods' pipe bits with the link in bits
    20-23 and the mouth in bits 5-6 (0 right, 1 left, 2 up, 3 down)."""
    return 0x6040000 | (link << 20) | (mouth << 5)


@test_level(130, "Pipe Trip")
def level_pipe_trip() -> LevelBuilder:
    """Both ways through a pipe, to the subworld and back.

    Overworld: a mouth-up pipe (link 1) at column 10, two tiles out of the
    ground; the player stands on it and presses down. Subworld (horizontal,
    the builder's 84 x 27): he rises out of a mouth-up pipe at column 6 (link
    1), walks right into the mouth of a sideways pipe lying on the floor with
    its mouth left at column 19 (link 2), and comes back up out of a mouth-up
    pipe at column 20 in the overworld (link 2). So one run has a downward
    entry, an upward exit, a sideways entry and the area change both ways.
    """
    b = LevelBuilder("Pipe Trip", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    b.objects.append({'id': OBJ_PIPE, 'x': 10, 'y': 5, 'width': 2, 'height': 2,
                      'flags': pipe_flags(1, 2)})
    b.objects.append({'id': OBJ_PIPE, 'x': 20, 'y': 5, 'width': 2, 'height': 2,
                      'flags': pipe_flags(2, 2)})
    for x in range(0, 40):
        b.sub_ground_tiles.append((x, 4))
    b.sub_objects.append({'id': OBJ_PIPE, 'x': 6, 'y': 5, 'width': 2, 'height': 2,
                          'flags': pipe_flags(1, 2)})
    # a sideways pipe's record sits on a tile centre, as The Lost Woods' do
    b.sub_objects.append({'id': OBJ_PIPE, 'x': 20, 'y': 5, 'width': 2, 'height': 2,
                          'flags': pipe_flags(2, 1), '_half_tile_offset': True})
    return b


@test_level(132, "Pipe Sides")
def level_pipe_sides() -> LevelBuilder:
    """The pipe directions Pipe Trip leaves out: spat out sideways, entered
    upward and dropped out of a ceiling pipe.

    Overworld: Pipe Trip's mouth-up pipe at column 10 (link 1). Subworld: he
    comes out of a mouth-right pipe on the floor at columns 6-7 (link 1),
    walks under a mouth-down pipe hanging with its mouth at row 7 (columns
    16-17, link 2) and jumps up into it; in the overworld he drops out of a
    mouth-down pipe hanging at row 8 (columns 19-20, link 2) onto the ground.
    """
    b = LevelBuilder("Pipe Sides", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    b.objects.append({'id': OBJ_PIPE, 'x': 10, 'y': 5, 'width': 2, 'height': 2,
                      'flags': pipe_flags(1, 2)})
    b.objects.append({'id': OBJ_PIPE, 'x': 20, 'y': 9, 'width': 2, 'height': 2,
                      'flags': pipe_flags(2, 3), '_half_tile_offset': True})
    for x in range(0, 40):
        b.sub_ground_tiles.append((x, 4))
    b.sub_objects.append({'id': OBJ_PIPE, 'x': 6, 'y': 6, 'width': 2, 'height': 2,
                          'flags': pipe_flags(1, 0), '_half_tile_offset': True})
    b.sub_objects.append({'id': OBJ_PIPE, 'x': 17, 'y': 8, 'width': 2, 'height': 2,
                          'flags': pipe_flags(2, 3), '_half_tile_offset': True})
    return b


@test_level(131, "Door Pair")
def level_door_pair() -> LevelBuilder:
    """Two doors on the ground, paired 0 and 1 in the overworld (doors pair
    2k with 2k+1 within one area; the flag words are The Lost Woods' own
    pair): the player walks to the door at column 10, presses up, comes out
    of the one at column 22, and goes back through it."""
    b = LevelBuilder("Door Pair", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    b.objects.append({'id': OBJ_DOOR, 'x': 10, 'y': 5, 'width': 1, 'height': 2,
                      'flags': 0x6000040, '_half_tile_offset': True})
    b.objects.append({'id': OBJ_DOOR, 'x': 22, 'y': 5, 'width': 1, 'height': 2,
                      'flags': 0x6100040, '_half_tile_offset': True})
    return b


def main():
    parser = argparse.ArgumentParser(description='Generate SMM2 test levels')
    parser.add_argument('--json', metavar='DIR',
                        help="Write each level as DIR/slot_N.json (parse_course --json shape); needs no save dir, writes no save")
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
    
    if args.json:
        out_dir = Path(args.json)
        out_dir.mkdir(parents=True, exist_ok=True)
        for slot in [args.slot] if args.slot is not None else sorted(TEST_LEVELS):
            if slot not in TEST_LEVELS:
                print(f"Slot {slot}: not defined, skipping")
                continue
            out_file = out_dir / f"slot_{slot}.json"
            out_file.write_text(level_json(TEST_LEVELS[slot][1]))
            print(f"Slot {slot}: Written {out_file}")
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


def _long_run(name: str, style: str) -> LevelBuilder:
    b = LevelBuilder(name, style, "Ground")
    b.width = 120
    b.add_ground_block(7, 109, y_surface=4, height=5)
    b.goal_y = 5
    return b


def _goal_pole(name: str, style: str) -> LevelBuilder:
    b = LevelBuilder(name, style, "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(116, "Goal Pole SMB1")
def level_goal_pole_smb1() -> LevelBuilder:
    """smm2-decomp item 6g (the goal as the game's): flat SMB1 ground up to
    the goal; Mario runs into the pole. Record with `player` and the
    `goaldemo` preset (the demo, its pole and the player's goal phase)."""
    return _goal_pole("Goal Pole SMB1", "SMB1")


@test_level(117, "Goal Pole NSMBU")
def level_goal_pole_nsmbu() -> LevelBuilder:
    """The Goal Pole course in NSMBU: the back jump off the pole."""
    return _goal_pole("Goal Pole NSMBU", "NSMBU")


@test_level(118, "Goal Pole 3DW")
def level_goal_pole_3dw() -> LevelBuilder:
    """The Goal Pole course in 3D World: its climb and back jump."""
    return _goal_pole("Goal Pole 3DW", "3DW")


@test_level(120, "Long Run NSMBU")
def level_long_run_nsmbu() -> LevelBuilder:
    """Recording batch 5 (smm2-decomp item 4, Walk's clips): the 120-tile
    runway in NSMBU: walk, run to the full dash, stop, stand."""
    return _long_run("Long Run NSMBU", "NSMBU")


@test_level(121, "Long Run 3DW")
def level_long_run_3dw() -> LevelBuilder:
    """Recording batch 5: the runway in 3D World (its clips and its rate)."""
    return _long_run("Long Run 3DW", "3DW")


@test_level(122, "Long Run SMB1")
def level_long_run_smb1() -> LevelBuilder:
    """Recording batch 5: the runway in SMB1 (the 2D styles' walk rate and
    the players object's +0x58)."""
    return _long_run("Long Run SMB1", "SMB1")


@test_level(123, "Tunnel 3DW")
def level_tunnel_3dw() -> LevelBuilder:
    """Recording batch 6 (smm2-decomp todo item 10, 3D World's shoulder
    moves): the runway in 3D World with a tunnel one row high at tiles
    25..35 (the ceiling on row 6), where small Mario's long jump is refused
    by the ceiling's probe, and a mushroom at tile 45, after which big Mario
    rolls back through the tunnel."""
    b = _runway("Tunnel 3DW", "3DW")
    b.add_ground_block(25, 35, y_surface=6, height=1)
    b.add_actor(OBJ_MUSHROOM, 45, 5)
    return b


@test_level(124, "Wall 3DW")
def level_wall_3dw() -> LevelBuilder:
    """Recording batch 6: the runway in 3D World with a wall 12 rows high at
    tiles 20..21, for the spin high jump into a wall and the wall slide in
    3D World."""
    b = _runway("Wall 3DW", "3DW")
    b.add_ground_block(20, 21, y_surface=16, height=12)
    return b


OBJ_BIG_MUSHROOM = 44   # the style's own power-up: SMB3's leaf, SMW's feather, NSMBU's propeller, 3D World's bell


@test_level(127, "Cat 3DW")
def level_cat_3dw() -> LevelBuilder:
    """Recording batch 8 (smm2-decomp todo item 9, the Cat): Wall 3DW's runway
    and wall with the style's own power-up (object 44, the Super Bell) at
    tile 8: the Cat's scratch, its dive, its slide, the climb up the wall."""
    b = _runway("Cat 3DW", "3DW")
    b.add_ground_block(20, 21, y_surface=16, height=12)
    b.add_actor(OBJ_BIG_MUSHROOM, 8, 5)
    return b


@test_level(125, "Cape SMW")
def level_cape_smw() -> LevelBuilder:
    """Recording batch 7 (smm2-decomp todo item 9, the suits): the 120-tile
    runway in SMW with the style's own power-up (object 44, the Cape
    Feather) at tile 8: the cape's spin, its flight from a full run, its
    float."""
    b = _long_run("Cape SMW", "SMW")
    b.add_actor(OBJ_BIG_MUSHROOM, 8, 8)   # a feather sways down through the ground: walk to it at once
    return b


@test_level(126, "Propeller NSMBU")
def level_propeller_nsmbu() -> LevelBuilder:
    """Recording batch 7: the 120-tile runway in NSMBU with object 44 (the
    Propeller Mushroom) at tile 8: the propeller's flight and its drill."""
    # A placed propeller sinks through the ground and drifts off during the
    # course's intro: it comes out of a ? block just over his head instead,
    # and he catches it as it floats down.
    b = _long_run("Propeller NSMBU", "NSMBU")
    b.objects.append({'id': OBJ_QUESTION, 'x': 8, 'y': 7, 'width': 1, 'height': 1, 'contents': OBJ_BIG_MUSHROOM})
    return b


if __name__ == '__main__':
    exit(main())
