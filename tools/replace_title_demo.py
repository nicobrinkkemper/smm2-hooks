#!/usr/bin/env python3
"""replace_title_demo.py — Replace title screen demo levels.

Title demos are Yaz0-compressed SARC archives containing a .bcd file.
This tool replaces the internal .bcd with a generated test level.

Usage:
    python3 replace_title_demo.py              # Replace all 10 title demos
    python3 replace_title_demo.py --slot 0     # Replace only demo 0
    python3 replace_title_demo.py --restore    # Restore original demos
"""

import struct
import argparse
from pathlib import Path
import shutil

# Import from gen_test_levels for level generation
from gen_test_levels import LevelBuilder, encrypt_course, STYLES, THEMES

EDEN_ROMFS = Path("/mnt/c/Users/nico/AppData/Roaming/eden/sdmc/atmosphere/contents/01009B90006DC000/romfs/Course")
EDEN_DUMP = Path("/mnt/c/Users/nico/AppData/Roaming/eden/dump/01009B90006DC000/romfs/Course")


def yaz0_decompress(data: bytes) -> bytes:
    """Decompress Yaz0 data using libyaz0."""
    import libyaz0
    return libyaz0.decompress(data)


def yaz0_compress(data: bytes) -> bytes:
    """Compress data with Yaz0 using libyaz0."""
    import libyaz0
    return libyaz0.compress(data)


def parse_sarc(data: bytes) -> dict:
    """Parse SARC archive, return dict of filename -> (offset, size)."""
    if data[:4] != b'SARC':
        raise ValueError('Not SARC format')
    
    header_size = struct.unpack('<H', data[4:6])[0]
    bom = struct.unpack('<H', data[6:8])[0]
    file_size = struct.unpack('<I', data[8:12])[0]
    data_offset = struct.unpack('<I', data[12:16])[0]
    
    # SFAT header at offset 0x14
    sfat_magic = data[0x14:0x18]
    sfat_header_size = struct.unpack('<H', data[0x18:0x1A])[0]
    node_count = struct.unpack('<H', data[0x1A:0x1C])[0]
    hash_key = struct.unpack('<I', data[0x1C:0x20])[0]
    
    # SFNT (string table) follows SFAT
    sfat_size = 0x0C + node_count * 0x10
    sfnt_offset = 0x14 + sfat_size
    
    files = {}
    for i in range(node_count):
        node_offset = 0x20 + i * 0x10
        name_hash = struct.unpack('<I', data[node_offset:node_offset+4])[0]
        name_offset = struct.unpack('<I', data[node_offset+4:node_offset+8])[0] & 0xFFFFFF
        file_start = struct.unpack('<I', data[node_offset+8:node_offset+12])[0]
        file_end = struct.unpack('<I', data[node_offset+12:node_offset+16])[0]
        
        # Read filename from SFNT
        str_offset = sfnt_offset + 8 + name_offset * 4
        name_end = data.find(b'\x00', str_offset)
        filename = data[str_offset:name_end].decode('utf-8')
        
        files[filename] = {
            'offset': data_offset + file_start,
            'size': file_end - file_start,
            'start': file_start,
            'end': file_end,
        }
    
    return {
        'data_offset': data_offset,
        'files': files,
        'raw': data,
    }


def replace_bcd_in_sarc(sarc_data: bytes, new_bcd: bytes) -> bytes:
    """Replace the .bcd file inside a SARC archive."""
    sarc = parse_sarc(sarc_data)
    
    # Find the .bcd file
    bcd_name = None
    for name in sarc['files']:
        if name.endswith('.bcd'):
            bcd_name = name
            break
    
    if not bcd_name:
        raise ValueError('No .bcd file found in SARC')
    
    bcd_info = sarc['files'][bcd_name]
    old_size = bcd_info['size']
    new_size = len(new_bcd)
    
    # For simplicity, require same size (BCD files are fixed size: 0x5C000)
    if new_size != old_size:
        raise ValueError(f'BCD size mismatch: expected {old_size}, got {new_size}')
    
    # Replace in-place
    output = bytearray(sarc_data)
    offset = bcd_info['offset']
    output[offset:offset + new_size] = new_bcd
    
    return bytes(output)


def create_flat_test_level() -> bytes:
    """Create a simple flat ground test level (encrypted BCD format).
    
    Start area is 7 tiles wide (x=0 to x=6).
    Goal area is ~4 tiles wide before goal_x.
    Safe zone: x >= 7 and x <= goal_x - 4
    """
    b = LevelBuilder("Test Level", "SMB1", "Ground")
    b.add_ground(7, 22, 4)  # Safe zone: after start area, before goal
    b.goal_x = 27
    b.goal_y = 5
    
    course_data = b.build()
    encrypted = encrypt_course(course_data)
    return encrypted


def replace_title_demo(slot: int, level_data: bytes):
    """Replace a single title demo slot."""
    szs_name = f"title_course_data_{slot:02d}.szs"
    
    # Get original from dump
    original_path = EDEN_DUMP / szs_name
    if not original_path.exists():
        raise FileNotFoundError(f"Original not found: {original_path}")
    
    # Read and decompress
    with open(original_path, 'rb') as f:
        compressed = f.read()
    
    sarc_data = yaz0_decompress(compressed)
    
    # Replace BCD
    new_sarc = replace_bcd_in_sarc(sarc_data, level_data)
    
    # Recompress
    new_compressed = yaz0_compress(new_sarc)
    
    # Write to mod folder
    EDEN_ROMFS.mkdir(parents=True, exist_ok=True)
    output_path = EDEN_ROMFS / szs_name
    
    with open(output_path, 'wb') as f:
        f.write(new_compressed)
    
    print(f"  Wrote {output_path.name} ({len(new_compressed)} bytes)")


def restore_original_demos():
    """Remove modded demos to restore originals."""
    if EDEN_ROMFS.exists():
        shutil.rmtree(EDEN_ROMFS)
        print("Removed modded title demos")
    else:
        print("No modded demos to remove")


def main():
    parser = argparse.ArgumentParser(description='Replace title screen demos')
    parser.add_argument('--slot', type=int, help='Replace only this slot (0-9)')
    parser.add_argument('--restore', action='store_true', help='Restore original demos')
    args = parser.parse_args()
    
    if args.restore:
        restore_original_demos()
        return 0
    
    # Create test level
    level_data = create_flat_test_level()
    print(f"Generated test level: {len(level_data)} bytes")
    
    slots = [args.slot] if args.slot is not None else range(10)
    
    for slot in slots:
        try:
            replace_title_demo(slot, level_data)
        except Exception as e:
            print(f"  Slot {slot} failed: {e}")
    
    print("\nDone! Restart Eden to see changes.")
    return 0


if __name__ == '__main__':
    exit(main())
