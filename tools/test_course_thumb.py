"""Tests for course_thumb: the thumbnail key table against a game-written file.

    python3 -m unittest tools/test_course_thumb.py   (from the repo root)

data/course_thumb_head.btl is a thumbnail the game wrote, cut to its first
cipher block plus the crypto config, so it holds the JPEG header and no
picture.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import course_thumb as ct  # noqa: E402

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

    def test_too_short(self):
        self.assertIsNone(ct.decrypt_thumb(self.data[-0x30:]))


if __name__ == '__main__':
    unittest.main()
