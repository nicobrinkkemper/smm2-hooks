"""Tests for course_thumb: key derivation against a game-written file, layout, copies.

    python3 -m unittest tools/test_course_thumb.py   (from the repo root)

data/course_thumb_head.btl is a thumbnail the game wrote, cut to its first
cipher block plus the crypto config: it checks the key derivation (the
16 table entries that file draws) and holds the JPEG header but no picture.
"""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import course_thumb as ct  # noqa: E402
from Crypto.Cipher import AES  # noqa: E402
from parse_course import SeadRandom, create_key  # noqa: E402

HEAD = os.path.join(HERE, '..', 'data', 'course_thumb_head.btl')


class DecryptThumb(unittest.TestCase):
    def setUp(self):
        with open(HEAD, 'rb') as f:
            self.data = f.read()

    def test_game_file_decrypts_to_jfif(self):
        self.assertEqual(ct.decrypt_thumb(self.data)[:11], b'\xff\xd8\xff\xe0\x00\x10JFIF\x00')

    def test_wrong_config_is_not_a_jpeg(self):
        damaged = self.data[:-0x20] + bytes(0x10) + self.data[-0x10:]  # zeroed random state
        self.assertIsNone(ct.decrypt_thumb(damaged))

    def test_whole_file_layout(self):
        # JPEG, zero padding, then the trailer: u32 length of what precedes it + 0x30 bytes.
        jpeg = b'\xff\xd8\xff\xe0' + b'\x11' * 60 + b'\xff\xd9'
        area = 0x200 - ct.TRAILER
        plain = jpeg + bytes(area - len(jpeg)) + struct.pack('<I', area) + b'\x22' * 0x30
        iv, state = b'\x33' * 16, (1, 2, 3, 4)
        key = create_key(SeadRandom(*state), ct.THUMB_KEY_TABLE, 0x10)
        body = AES.new(key, AES.MODE_CBC, iv).encrypt(plain)
        config = iv + struct.pack('<4I', *state) + bytes(0x10)
        self.assertEqual(ct.decrypt_thumb(body + config), jpeg)

    def test_too_short(self):
        self.assertIsNone(ct.decrypt_thumb(self.data[-0x30:]))


class CopiedFrom(unittest.TestCase):
    def test_equal_files_are_copies(self):
        with tempfile.TemporaryDirectory() as d:
            for name, body in [('course_thumb_036.btl', b'a' * 64), ('course_thumb_005.btl.orig', b'a' * 64),
                               ('course_thumb_036.btl.orig', b'a' * 64),
                               ('course_thumb_001.btl', b'b' * 64), ('course_data_000.bcd', b'a' * 64)]:
                with open(os.path.join(d, name), 'wb') as f:
                    f.write(body)
            self.assertEqual(ct.copied_from(os.path.join(d, 'course_thumb_036.btl'), b'a' * 64),
                             ['course_thumb_005.btl.orig'])
            self.assertEqual(ct.copied_from(os.path.join(d, 'course_thumb_001.btl'), b'b' * 64), [])


if __name__ == '__main__':
    unittest.main()
