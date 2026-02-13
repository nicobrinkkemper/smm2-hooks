#!/usr/bin/env python3
"""Parse SMM2 course data (.bcd) files.

Decrypts and parses Super Mario Maker 2 course files from Ryujinx save data.
Outputs level geometry (actors, tiles, ground) for bot navigation.

Usage:
    python3 parse_course.py [slot_number]
    python3 parse_course.py --list          # list all courses
    python3 parse_course.py 75              # parse slot 75
    python3 parse_course.py 75 --json       # output as JSON
    python3 parse_course.py 75 --map        # ASCII map
"""

import struct, zlib, os, sys, json, argparse
from Crypto.Cipher import AES
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# sead::Random (Nintendo's PRNG)
# ============================================================================
class SeadRandom:
    def __init__(self, s0, s1, s2, s3):
        self.state = [s0, s1, s2, s3]

    def u32(self):
        s = self.state
        temp = (s[0] ^ ((s[0] << 11) & 0xFFFFFFFF)) & 0xFFFFFFFF
        temp ^= temp >> 8
        temp ^= s[3]
        temp ^= s[3] >> 19
        s[0] = s[1]; s[1] = s[2]; s[2] = s[3]; s[3] = temp
        return temp

    def uint(self, max_val):
        return (self.u32() * max_val) >> 32


# ============================================================================
# ENL key derivation
# ============================================================================
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


# ============================================================================
# Course decryption
# ============================================================================
def decrypt_course(path):
    """Decrypt a .bcd file, return raw decrypted bytes or None on CRC fail."""
    with open(path, 'rb') as f:
        data = f.read()

    header = data[:0x10]
    encrypted = data[0x10:0x10 + 0x5BFC0]
    crypto_config = data[0x10 + 0x5BFC0:]

    iv = crypto_config[:0x10]
    random_state = crypto_config[0x10:0x20]

    context = struct.unpack('<IIII', random_state)
    rand = SeadRandom(*context)
    key = create_key(rand, COURSE_KEY_TABLE, 0x10)

    aes = AES.new(key, AES.MODE_CBC, iv)
    decrypted = aes.decrypt(encrypted)

    stored_crc = struct.unpack_from('<I', header, 0x08)[0]
    calc_crc = zlib.crc32(decrypted) & 0xFFFFFFFF
    if stored_crc != calc_crc:
        return None
    return decrypted


# ============================================================================
# Course format constants
# ============================================================================
STYLES = {'M1': 'SMB1', 'M3': 'SMB3', 'MW': 'SMW', 'WU': 'NSMBU', '3W': '3DW'}
THEMES = ['Ground', 'Underground', 'Castle', 'Airship', 'Underwater',
          'Ghost', 'Snow', 'Desert', 'Sky', 'Forest']

# Actor type IDs (from community research)
ACTOR_NAMES = {
    0: 'Goomba', 1: 'Koopa', 2: 'PiranhaPlant', 3: 'HammerBro',
    4: 'Block', 5: 'QuestionBlock', 6: 'HardBlock', 7: 'Ground',
    8: 'Coin', 9: 'Pipe', 10: 'Spring', 11: 'Lift',
    12: 'Thwomp', 13: 'BulletBillBlaster', 14: 'Mushroom', 15: 'Bob-omb',
    16: 'Cloud', 17: 'Vine', 18: 'OneCoin', 19: 'Donut',
    20: 'Bridge', 21: 'P-Switch', 22: 'POWBlock', 23: 'SuperMushroom',
    24: 'Note', 25: 'SemisolidPlatform', 26: 'BeanstalkHouse', 27: 'Door',
    28: 'Spike', 29: 'GroundGoal', 30: 'GoalPole', 31: 'Arrow',
    32: 'OneWay', 33: 'Saw', 34: 'Player', 35: 'BigMushroom',
    36: 'Shoe/Yoshi', 37: 'DryBones', 38: 'Cannon', 39: 'Blooper',
    40: 'CastleBridge', 41: 'JumpDai', 42: 'Skewer', 43: 'SnakeBlock',
    44: 'IceBlock', 45: 'Claw', 46: 'Bumper', 47: 'Lakitu',
    48: 'LakituCloud', 49: 'Boo', 50: 'Toad/ToadHouse', 51: 'ChainChomp',
    52: 'Sledge/SumoWrestle', 53: 'Thwimp', 54: 'Monty', 55: 'FishBone',
    56: 'Muncher', 57: 'Wiggler', 58: 'Spiny', 59: 'FireBar',
    60: 'Checkpoint', 61: 'BeltConveyor', 62: 'Burner', 63: 'WarpDoor',
    64: 'Jelectro', 65: 'Kamek', 66: 'HP', 67: 'FastLava',
    68: 'Mechakoopa', 69: 'Crate', 70: 'MushroomTrampoline', 71: 'Key',
    72: 'AntTrooper', 73: 'Spike(enemy)', 74: 'SpikeTop', 75: 'SlopeL45',
    76: 'SlopeR45', 77: 'SlopeL30', 78: 'SlopeR30', 79: 'Star',
    80: 'Icicle', 81: 'ClimateChange', 82: 'SwitchBlock', 83: 'OnOffBlock',
    84: 'DashBlock', 85: 'Porcupuffer', 86: 'Track', 87: 'TreePlatform',
    88: 'SemisolidMushroom', 89: 'Tornado', 90: 'ClearPipe', 91: 'TenCoin',
    92: '30Coin', 93: '50Coin', 94: 'P-Balloon',
}


# ============================================================================
# Course parsing
# ============================================================================
def parse_header(dec):
    """Parse course header (first 0x200 bytes)."""
    h = {}
    h['start_y'] = dec[0]
    h['goal_y'] = dec[1]
    h['goal_x'] = struct.unpack_from('<H', dec, 2)[0]
    h['time_limit'] = struct.unpack_from('<H', dec, 4)[0]
    h['year'] = struct.unpack_from('<H', dec, 8)[0]
    h['month'] = dec[10]
    h['day'] = dec[11]
    h['hour'] = dec[12]
    h['minute'] = dec[13]
    h['style'] = dec[0xF1:0xF3].decode('ascii', errors='?')
    h['style_name'] = STYLES.get(h['style'], h['style'])
    h['name'] = dec[0xF4:0xF4 + 0x42].decode('utf-16-le', errors='ignore').split('\x00')[0]
    h['description'] = dec[0x136:0x136 + 0xCA].decode('utf-16-le', errors='ignore').split('\x00')[0]
    return h


def parse_area(area_data):
    """Parse a course area (overworld or subworld)."""
    a = {}
    a['theme'] = area_data[0]
    a['theme_name'] = THEMES[area_data[0]] if area_data[0] < len(THEMES) else str(area_data[0])
    a['autoscroll_type'] = area_data[1]
    a['orientation'] = area_data[3]

    # Boundaries
    a['bound_right'] = struct.unpack_from('<I', area_data, 0x08)[0]
    a['bound_top'] = struct.unpack_from('<I', area_data, 0x0C)[0]
    a['bound_left'] = struct.unpack_from('<I', area_data, 0x10)[0]
    a['bound_bottom'] = struct.unpack_from('<I', area_data, 0x14)[0]

    # Counts
    a['actor_count'] = struct.unpack_from('<I', area_data, 0x1C)[0]
    a['tile_count'] = struct.unpack_from('<I', area_data, 0x3C)[0]

    # Parse actors
    actors = []
    for i in range(min(a['actor_count'], 2600)):
        off = 0x48 + i * 0x20
        raw = area_data[off:off + 0x20]
        if len(raw) < 0x20:
            break
        x = struct.unpack_from('<i', raw, 0)[0] / 10.0
        y = struct.unpack_from('<i', raw, 4)[0] / 10.0
        w = raw[0x0A] + 1  # stored as 0-indexed
        h = raw[0x0B] + 1
        flags = struct.unpack_from('<I', raw, 0x0C)[0]
        obj_type = struct.unpack_from('<H', raw, 0x18)[0]
        name = ACTOR_NAMES.get(obj_type, f'unk_{obj_type}')
        actors.append({
            'type': obj_type, 'name': name,
            'x': x, 'y': y, 'w': w, 'h': h,
            'flags': flags,
        })
    a['actors'] = actors

    # Parse tiles
    # Layout: header(0x48) + actors(0x14820) + otoasobi(0x4B0) + snake(0x12EC)
    #       + dokan(0xE420) + pakkun(0x348) + bikkuri(0x1B8) + orbit(0x1B8)
    TILE_OFFSET = 0x247A4
    tiles = []
    for i in range(min(a['tile_count'], 4000)):
        off = TILE_OFFSET + i * 4
        raw = area_data[off:off + 4]
        if len(raw) < 4:
            break
        x, y = raw[0], raw[1]
        tile_id = struct.unpack_from('<H', raw, 2)[0]
        tiles.append({'x': x, 'y': y, 'id': tile_id})
    a['tiles'] = tiles
    return a


def parse_course(dec):
    """Parse full decrypted course data."""
    course = {}
    course['header'] = parse_header(dec)
    course['overworld'] = parse_area(dec[0x200:0x200 + 0x2DEE0])
    course['subworld'] = parse_area(dec[0x200 + 0x2DEE0:0x200 + 2 * 0x2DEE0])
    return course


# ============================================================================
# ASCII map renderer
# ============================================================================
def render_map(area, width=120, height=30):
    """Render a tile-based ASCII map of the area."""
    tiles = area.get('tiles', [])
    actors = area.get('actors', [])

    if not tiles and not actors:
        print("  (empty area)")
        return

    # For tile map, use direct tile coordinates (each tile = 1 grid cell)
    if tiles:
        max_x = max(t['x'] for t in tiles)
        max_y = max(t['y'] for t in tiles)

        # Scale to fit terminal
        scale_x = max(1, (max_x + 2) // width + 1) if max_x >= width else 1
        cols = min(max_x + 2, width)
        rows = max_y + 2

        grid = [[' '] * cols for _ in range(rows)]

        for t in tiles:
            gx = t['x'] // scale_x
            gy = t['y']
            if 0 <= gx < cols and 0 <= gy < rows:
                grid[gy][gx] = '#'

        # Place actors on tile grid (convert from position units to tile units)
        for a in actors:
            gx = int(a['x'] / 16) // scale_x
            gy = int(a['y'] / 16)
            if 0 <= gx < cols and 0 <= gy < rows:
                char = '*'
                t = a['type']
                if t in (0, 1, 2, 3): char = 'E'
                elif t in (9,): char = 'P'
                elif t in (30,): char = 'G'
                elif t in (34,): char = 'M'
                elif t in (8, 18, 91): char = 'c'
                grid[gy][gx] = char

        # Print Y-inverted (y=0 at bottom)
        for y in range(rows - 1, -1, -1):
            print(f'{y:2d}|' + ''.join(grid[y]))
        print(f'  +' + '-' * cols)
        if scale_x > 1:
            print(f'  (scale: 1 char = {scale_x} tiles)')
    else:
        # Actor-only map (use position coordinates)
        min_x = min(a['x'] for a in actors)
        max_x = max(a['x'] for a in actors) or 1
        min_y = min(a['y'] for a in actors)
        max_y = max(a['y'] for a in actors) or 1

        x_range = max_x - min_x or 1
        y_range = max_y - min_y or 1

        grid = [[' '] * width for _ in range(height)]

        for a in actors:
            cx = int((a['x'] - min_x) / x_range * (width - 1))
            cy = int((a['y'] - min_y) / y_range * (height - 1))
            cx = max(0, min(width - 1, cx))
            cy = max(0, min(height - 1, cy))

            char = '#'
            t = a['type']
            if t in (6,): char = 'H'
            elif t in (25, 88): char = '-'
            elif t in (9,): char = 'P'
            elif t in (30,): char = 'G'
            elif t in (34,): char = 'M'
            elif t in (0, 1, 2, 3): char = 'E'
            grid[cy][cx] = char

        for y in range(height - 1, -1, -1):
            print(''.join(grid[y]))
        print(f"  x: {min_x:.0f} to {max_x:.0f}  y: {min_y:.0f} to {max_y:.0f}")


# ============================================================================
# Main
# ============================================================================
def get_save_path():
    """Get Ryujinx save data path."""
    # Check .env first
    p = os.environ.get('RYUJINX_SAVE_PATH', '')
    if p and os.path.isdir(p):
        return p
    # Default Ryujinx path (Windows via WSL)
    default = '/mnt/c/Users/nico/AppData/Roaming/Ryujinx/bis/user/save/0000000000000001/0'
    if os.path.isdir(default):
        return default
    return None


def main():
    parser = argparse.ArgumentParser(description='Parse SMM2 course data')
    parser.add_argument('slot', nargs='?', type=int, help='Course slot number')
    parser.add_argument('--list', action='store_true', help='List all courses')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--map', action='store_true', help='Show ASCII map')
    parser.add_argument('--actors', action='store_true', help='List all actors')
    parser.add_argument('--tiles', action='store_true', help='List all tiles')
    parser.add_argument('--save-dir', type=str, help='Override save directory')
    args = parser.parse_args()

    save_dir = args.save_dir or get_save_path()
    if not save_dir:
        print("Error: Cannot find Ryujinx save directory. Set RYUJINX_SAVE_PATH in .env", file=sys.stderr)
        sys.exit(1)

    if args.list or args.slot is None:
        # List all courses
        for i in range(180):
            path = os.path.join(save_dir, f'course_data_{i:03d}.bcd')
            if not os.path.exists(path):
                break
            dec = decrypt_course(path)
            if dec is None:
                continue
            h = parse_header(dec)
            area = parse_area(dec[0x200:0x200 + 0x2DEE0])
            print(f"{i:3d}: \"{h['name']}\" {h['style_name']} {area['theme_name']} actors={area['actor_count']}")
        return

    # Parse specific slot
    path = os.path.join(save_dir, f'course_data_{args.slot:03d}.bcd')
    if not os.path.exists(path):
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    dec = decrypt_course(path)
    if dec is None:
        print("Error: CRC mismatch (wrong key table or corrupted file)", file=sys.stderr)
        sys.exit(1)

    course = parse_course(dec)

    if args.json:
        print(json.dumps(course, indent=2, default=str))
        return

    # Pretty print
    h = course['header']
    ow = course['overworld']
    sw = course['subworld']

    print(f"Course: \"{h['name']}\"")
    if h['description']:
        print(f"  Description: {h['description']}")
    print(f"  Style: {h['style_name']}  Theme: {ow['theme_name']}")
    print(f"  Time: {h['time_limit']}s  Goal: ({h['goal_x']}, {h['goal_y']})")
    print(f"  Date: {h['year']}-{h['month']:02d}-{h['day']:02d} {h['hour']:02d}:{h['minute']:02d}")
    print(f"  Overworld: {ow['actor_count']} actors, {ow['tile_count']} tiles")
    print(f"  Subworld:  {sw['actor_count']} actors, {sw['tile_count']} tiles")

    if args.actors:
        print(f"\nOverworld actors:")
        for i, a in enumerate(ow['actors']):
            print(f"  [{i:3d}] {a['name']:20s} ({a['x']:7.1f},{a['y']:6.1f}) {a['w']}x{a['h']} flags=0x{a['flags']:08x}")

    if args.tiles:
        print(f"\nOverworld tiles:")
        for i, t in enumerate(ow['tiles']):
            print(f"  [{i:3d}] ({t['x']:3d},{t['y']:3d}) id=0x{t['id']:04x}")

    if args.map:
        print(f"\nOverworld map:")
        render_map(ow)


if __name__ == '__main__':
    main()
