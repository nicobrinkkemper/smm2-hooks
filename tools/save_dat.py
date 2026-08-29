#!/usr/bin/env python3
"""Read and write Super Mario Maker 2 save.dat (the Coursebot slot index).

Layout (verified against v3.0.3 main.elf, save writer at 0x7100E76E90,
save reader at 0x7100E78430, and the real file):

    0x0000  u32 1, u32 0xB, u32 crc32(body[:0xB910]), u32 0
    0x0010  body, 0xBFC0 bytes, AES-128-CBC with key table SAVE_KEY_TABLE
    0xBFD0  iv[16], rand seed[16], AES-CMAC[16] over the plaintext body

Inside the body:

    0xB910  u32 2, u32 0, u32 crc32(body[0xB920:0xB920+0x6A0]), u32 0
    0xB920  180 records of 8 bytes: slot id, used flag, 6 zero bytes

The game only shows a Coursebot slot whose used flag is 1; the .bcd on disk
is never consulted for that. Usage:

    python3 save_dat.py list [--save-dir DIR]
    python3 save_dat.py mark-used SLOT [SLOT ...] [--save-dir DIR]
    python3 save_dat.py mark-empty SLOT [SLOT ...] [--save-dir DIR]
    python3 save_dat.py decrypt OUT.bin [--save-dir DIR]

mark-* backs up the previous file once as save.dat.orig and keeps a dated
.bak for every write. Restart the game afterwards; it caches the index.
"""
import argparse
import os
import random
import shutil
import struct
import sys
import time
import zlib

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

sys.argv, _argv = ['x'], sys.argv
from gen_test_levels import SeadRandom, create_key  # noqa: E402
sys.argv = _argv

SAVE_KEY_TABLE = [
    0x5C736064, 0x3F9178C3, 0x9D11DBD3, 0xD8B11DE9, 0xBCAFD10B, 0x85E013EB, 0xAB4CB7A5, 0x12DF234A,
    0x69BD8F28, 0x9718796A, 0x467E510E, 0xC9002264, 0xF5EF9EF5, 0xFE19683B, 0x9E739A59, 0x8330F69F,
    0x158E467C, 0xDCC25B0B, 0xCC96E901, 0x5AFF8BE1, 0xBB08745E, 0xF9C232E5, 0xDB7E0641, 0x9B5E1AD7,
    0x25B8D979, 0xE35251D3, 0x9C1E9ADB, 0x256902E2, 0xCA67B195, 0x16CDB407, 0xFD95C734, 0xD019C133,
    0x5F39E755, 0x118168FC, 0xAA796804, 0xC9AC1148, 0x2EC0C6B4, 0xDE6E18F6, 0x5F7FAA46, 0x09FAE6A3,
    0x6BF9D926, 0xD41D2628, 0xC91BD99B, 0xB4F43F73, 0x37B8C265, 0xA8AD2CDB, 0xF2F7A186, 0x4842B092,
    0xC6C69499, 0x5171F6D5, 0xB21A4FA7, 0x7E97D996, 0x6FD8C33C, 0x5C9A8698, 0x7BB249D5, 0x0D43D9B4,
    0xAAAC5F3D, 0x264A8038, 0x8DF13471, 0x1C912EC2, 0xB5D226E7, 0x807803C2, 0xD07EC9D7, 0x8ED952BB,
]

SIZE = 0xC000
BODY = 0xBFC0
RECORDS = 0xB920
RECORD_COUNT = 180
SECTION = 0xB910


def default_save_dir():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
    return os.environ.get('EDEN_SAVE_DIR') or os.environ.get('SAVE_DIR')


def decrypt(raw: bytes) -> bytes:
    if len(raw) != SIZE:
        raise ValueError(f'save.dat is {len(raw):#x} bytes, expected {SIZE:#x}')
    cfg = raw[-0x30:]
    rand = SeadRandom(*struct.unpack('<4I', cfg[16:32]))
    key1 = create_key(rand, SAVE_KEY_TABLE, 16)
    body = AES.new(key1, AES.MODE_CBC, cfg[:16]).decrypt(raw[0x10:-0x30])
    key2 = create_key(rand, SAVE_KEY_TABLE, 16)
    mac = CMAC.new(key2, ciphermod=AES)
    mac.update(body)
    if mac.digest() != cfg[32:48]:
        raise ValueError('CMAC mismatch: not a v3.0.3 save.dat or wrong key table')
    if zlib.crc32(body[:SECTION]) & 0xFFFFFFFF != struct.unpack_from('<I', raw, 8)[0]:
        raise ValueError('header CRC mismatch')
    return body


def encrypt(body: bytes) -> bytes:
    body = bytearray(body)
    struct.pack_into('<I', body, SECTION + 8, zlib.crc32(body[RECORDS:RECORDS + 0x6A0]) & 0xFFFFFFFF)
    seed = bytes(random.randint(0, 255) for _ in range(16))
    iv = bytes(random.randint(0, 255) for _ in range(16))
    rand = SeadRandom(*struct.unpack('<4I', seed))
    key1 = create_key(rand, SAVE_KEY_TABLE, 16)
    enc = AES.new(key1, AES.MODE_CBC, iv).encrypt(bytes(body))
    key2 = create_key(rand, SAVE_KEY_TABLE, 16)
    mac = CMAC.new(key2, ciphermod=AES)
    mac.update(bytes(body))
    header = struct.pack('<4I', 1, 0xB, zlib.crc32(body[:SECTION]) & 0xFFFFFFFF, 0)
    return header + enc + iv + seed + mac.digest()


def records(body):
    return [(body[RECORDS + 8 * i], body[RECORDS + 8 * i + 1]) for i in range(RECORD_COUNT)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['list', 'mark-used', 'mark-empty', 'decrypt'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--save-dir', default=None)
    a = ap.parse_args()
    save_dir = a.save_dir or default_save_dir()
    if not save_dir:
        sys.exit('no save dir: pass --save-dir or set EDEN_SAVE_DIR in .env')
    path = os.path.join(save_dir, 'save.dat')
    body = decrypt(open(path, 'rb').read())

    if a.cmd == 'list':
        used = [s for s, f in records(body) if f]
        print('used slots:', used)
        return
    if a.cmd == 'decrypt':
        open(a.args[0], 'wb').write(body)
        print('wrote', a.args[0])
        return

    body = bytearray(body)
    for s in map(int, a.args):
        if not 0 <= s < RECORD_COUNT:
            sys.exit(f'slot {s} out of range')
        body[RECORDS + 8 * s + 1] = 1 if a.cmd == 'mark-used' else 0
    orig = path + '.orig'
    if not os.path.exists(orig):
        shutil.copy2(path, orig)
    shutil.copy2(path, path + time.strftime('.%Y%m%d-%H%M%S.bak'))
    open(path, 'wb').write(encrypt(bytes(body)))
    print('used slots now:', [s for s, f in records(decrypt(open(path, 'rb').read())) if f])


if __name__ == "__main__":
    main()
