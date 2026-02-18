#!/usr/bin/env python3
"""Replace title screen demo levels with generated test levels.

Usage:
    python3 replace_title_demos.py                    # Replace all 10 with SMB1/Ground
    python3 replace_title_demos.py --style SMB3      # Replace all 10 with SMB3/Ground
    python3 replace_title_demos.py --vary            # Each slot gets different style
"""

import argparse
import shutil
from pathlib import Path
import libyaz0
import sarc
import struct

# Import from gen_level
import sys
sys.path.insert(0, str(Path(__file__).parent))
from gen_level import create_minimal_course, encrypt_course, STYLES, THEMES

ROMFS_COURSE = Path("/mnt/c/Users/nico/AppData/Roaming/eden/dump/01009B90006DC000/romfs/Course")
EDEN_MODS = Path("/mnt/c/Users/nico/AppData/Roaming/eden/sdmc/atmosphere/contents/01009B90006DC000/romfs/Course")

STYLE_ORDER = ['SMB1', 'SMB3', 'SMW', 'NSMBU', '3DW', 'SMB1', 'SMB3', 'SMW', 'NSMBU', '3DW']
THEME_ORDER = ['Ground', 'Underground', 'Castle', 'Ghost', 'Sky', 'Snow', 'Desert', 'Forest', 'Airship', 'Underwater']


def create_szs(bcd_data: bytes, internal_name: str) -> bytes:
    """Create a Yaz0-compressed SARC containing the BCD."""
    # Build SARC manually (simple single-file archive)
    # SARC format: header + SFAT + SFNT + file data
    
    filename = internal_name.encode('utf-8') + b'\x00'
    # Align filename to 4 bytes
    while len(filename) % 4 != 0:
        filename += b'\x00'
    
    # Calculate offsets
    sarc_header_size = 0x14
    sfat_header_size = 0x0C
    sfat_entry_size = 0x10
    sfnt_header_size = 0x08
    
    data_offset = sarc_header_size + sfat_header_size + sfat_entry_size + sfnt_header_size + len(filename)
    # Align data to 0x100
    data_offset = (data_offset + 0xFF) & ~0xFF
    
    total_size = data_offset + len(bcd_data)
    
    # Build SARC header
    sarc_header = bytearray(sarc_header_size)
    sarc_header[0:4] = b'SARC'
    struct.pack_into('<H', sarc_header, 0x04, sarc_header_size)  # Header size
    struct.pack_into('<H', sarc_header, 0x06, 0xFEFF)            # BOM
    struct.pack_into('<I', sarc_header, 0x08, total_size)        # File size
    struct.pack_into('<I', sarc_header, 0x0C, data_offset)       # Data offset
    struct.pack_into('<H', sarc_header, 0x10, 0x0100)            # Version
    struct.pack_into('<H', sarc_header, 0x12, 0x0000)            # Reserved
    
    # Build SFAT header
    sfat_header = bytearray(sfat_header_size)
    sfat_header[0:4] = b'SFAT'
    struct.pack_into('<H', sfat_header, 0x04, sfat_header_size)  # Header size
    struct.pack_into('<H', sfat_header, 0x06, 1)                 # Node count
    struct.pack_into('<I', sfat_header, 0x08, 0x00000065)        # Hash key
    
    # Build SFAT entry
    def calc_hash(name: str) -> int:
        h = 0
        for c in name:
            h = (h * 0x65) + ord(c)
            h &= 0xFFFFFFFF
        return h
    
    sfat_entry = bytearray(sfat_entry_size)
    struct.pack_into('<I', sfat_entry, 0x00, calc_hash(internal_name))  # Name hash
    struct.pack_into('<I', sfat_entry, 0x04, 0x01000000)                # Flags + name offset
    struct.pack_into('<I', sfat_entry, 0x08, 0)                         # Data start
    struct.pack_into('<I', sfat_entry, 0x0C, len(bcd_data))             # Data end
    
    # Build SFNT header
    sfnt_header = bytearray(sfnt_header_size)
    sfnt_header[0:4] = b'SFNT'
    struct.pack_into('<H', sfnt_header, 0x04, sfnt_header_size)  # Header size
    struct.pack_into('<H', sfnt_header, 0x06, 0x0000)            # Reserved
    
    # Combine
    arc = bytearray(total_size)
    offset = 0
    arc[offset:offset+len(sarc_header)] = sarc_header
    offset += len(sarc_header)
    arc[offset:offset+len(sfat_header)] = sfat_header
    offset += len(sfat_header)
    arc[offset:offset+len(sfat_entry)] = sfat_entry
    offset += len(sfat_entry)
    arc[offset:offset+len(sfnt_header)] = sfnt_header
    offset += len(sfnt_header)
    arc[offset:offset+len(filename)] = filename
    
    # Write data at data_offset
    arc[data_offset:data_offset+len(bcd_data)] = bcd_data
    
    # Compress with Yaz0
    return libyaz0.compress(bytes(arc))


def replace_title_demo(slot: int, style: str, theme: str, dry_run: bool = False):
    """Replace a single title demo slot."""
    style_id = STYLES[style]
    theme_id = THEMES[theme]
    
    # Generate course
    course_data = create_minimal_course(style_id, theme_id)
    bcd_data = encrypt_course(course_data)
    
    # Create SZS
    internal_name = f"title_course_data_{slot:02d}.bcd"
    szs_data = create_szs(bcd_data, internal_name)
    
    # Output path (to mods folder)
    EDEN_MODS.mkdir(parents=True, exist_ok=True)
    out_path = EDEN_MODS / f"title_course_data_{slot:02d}.szs"
    
    print(f"Slot {slot}: {style}/{theme} -> {out_path.name} ({len(szs_data)} bytes)")
    
    if not dry_run:
        with open(out_path, 'wb') as f:
            f.write(szs_data)


def main():
    parser = argparse.ArgumentParser(description='Replace title screen demo levels')
    parser.add_argument('--style', type=str, default=None, choices=list(STYLES.keys()),
                        help='Use same style for all (default: vary)')
    parser.add_argument('--theme', type=str, default=None, choices=list(THEMES.keys()),
                        help='Use same theme for all (default: vary)')
    parser.add_argument('--vary', action='store_true', help='Each slot gets different style/theme')
    parser.add_argument('--dry-run', action='store_true', help="Don't write files")
    parser.add_argument('--slot', type=int, default=None, choices=range(10),
                        help='Only replace one slot')
    args = parser.parse_args()
    
    print(f"Output: {EDEN_MODS}")
    print()
    
    if args.slot is not None:
        # Single slot
        style = args.style or 'SMB1'
        theme = args.theme or 'Ground'
        replace_title_demo(args.slot, style, theme, args.dry_run)
    else:
        # All slots
        for i in range(10):
            if args.vary or (args.style is None and args.theme is None):
                style = STYLE_ORDER[i]
                theme = THEME_ORDER[i]
            else:
                style = args.style or 'SMB1'
                theme = args.theme or 'Ground'
            replace_title_demo(i, style, theme, args.dry_run)
    
    if not args.dry_run:
        print(f"\nDone! Restart Eden to see changes on title screen.")


if __name__ == '__main__':
    main()
