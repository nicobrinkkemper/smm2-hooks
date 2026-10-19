#!/usr/bin/env python3
"""Decrypt SMM2 course thumbnails (course_thumb_NNN.btl) to JPEG.

Each save slot keeps the game's own picture of its course next to the course
data: a 640x360 JPEG, zero-padded and encrypted the way course_data .bcd is
(AES-CBC, key from sead::Random over a key table), with the 0x30-byte crypto
config (iv, random state, cmac) at the end of the file. The decrypted area
is the JPEG, zeros up to a 0x34-byte trailer, then the trailer. The thumbnail key
table sits 0x610 bytes after the course one in the v3.0.3 main executable.

Usage:
    python3 course_thumb.py 36 /tmp/slot_36.jpg
    python3 course_thumb.py 36 /tmp/slot_36.jpg --save-dir /path/to/save
"""

import argparse
import os
import struct
import sys

from Crypto.Cipher import AES

from parse_course import SeadRandom, create_key, get_save_path

THUMB_KEY_TABLE = [
    0x39B399D2, 0xFAE40B38, 0x851BC213, 0x8CB4E3D9,
    0x7ED1C46A, 0xE8050462, 0xD8D24F76, 0xB52886FC,
    0x67890BF0, 0xF5329CB0, 0xD597FB28, 0x2B8EE0EA,
    0x47574C51, 0x0F7569D9, 0xCF1163AE, 0xE4A153BF,
    0xD1FAE468, 0xD4C64738, 0x360106F5, 0xDD7EB113,
    0xC296F3E2, 0x2C58F258, 0x79B554E1, 0x85DF9D06,
    0xAA307330, 0x01410F69, 0xB2F2C573, 0x82B93EB1,
    0xF351A11C, 0x63098693, 0x885B5DA5, 0x8872A8ED,
    0xACD9CB13, 0xED7FBCAD, 0xE6A41EC2, 0x5F44E79F,
    0x8346F5B5, 0x389FE6ED, 0x507124B5, 0xE9B23EAA,
    0x577113F0, 0xA95ED917, 0x2F62D158, 0x47843F86,
    0xC65637D0, 0x2F272052, 0xBA4A4CC4, 0xB5F146F6,
    0x501B87A7, 0x51FC3A93, 0x6EDE3F02, 0x3D265728,
    0x9B809440, 0x75B89229, 0xF6A280CC, 0x8537FA68,
    0x5B5ED19A, 0x6FC05BB6, 0xF4EF5261, 0xAA1B7D4F,
    0xFCB26110, 0x00AD3D74, 0xC0E73A4B, 0xF132E7C7,
]

CRYPTO_CONFIG = 0x30
TRAILER = 0x34


def decrypt_thumb(data):
    """The JPEG inside an encrypted thumbnail, or None when there is none (a
    blank thumbnail decrypts to zeros) or the data is not a thumbnail."""
    body, config = data[:-CRYPTO_CONFIG], data[-CRYPTO_CONFIG:]
    if len(config) != CRYPTO_CONFIG or not body or len(body) % 16:
        return None
    iv, state = config[:0x10], struct.unpack('<4I', config[0x10:0x20])
    key = create_key(SeadRandom(*state), THUMB_KEY_TABLE, 0x10)
    plain = AES.new(key, AES.MODE_CBC, iv).decrypt(body)
    # A whole file's plaintext ends in a 0x34-byte trailer: u32 length of the
    # picture area before it, then 0x30 bytes not used here.
    if len(plain) > TRAILER and struct.unpack_from('<I', plain, len(plain) - TRAILER)[0] == len(plain) - TRAILER:
        plain = plain[:-TRAILER]
    jpeg = plain.rstrip(b'\0')
    return jpeg if jpeg.startswith(b'\xff\xd8\xff') else None


def main():
    parser = argparse.ArgumentParser(description='Decrypt an SMM2 course thumbnail to JPEG')
    parser.add_argument('slot', type=int, help='Course slot number')
    parser.add_argument('out', help='JPEG to write')
    parser.add_argument('--save-dir', type=str, help='Override save directory')
    args = parser.parse_args()

    save_dir = args.save_dir or get_save_path()
    if not save_dir:
        print("Error: no save directory found; pass --save-dir", file=sys.stderr)
        sys.exit(1)
    path = os.path.join(save_dir, f'course_thumb_{args.slot:03d}.btl')
    if not os.path.exists(path):
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)
    with open(path, 'rb') as f:
        jpeg = decrypt_thumb(f.read())
    if jpeg is None:
        print(f"Error: {path} holds no JPEG (a blank thumbnail or not a thumbnail)", file=sys.stderr)
        sys.exit(1)
    with open(args.out, 'wb') as f:
        f.write(jpeg)


if __name__ == '__main__':
    main()
