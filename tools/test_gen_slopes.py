"""Every generated course's slope records are ones the game writes.

    python3 -m unittest tools/test_gen_slopes.py   (from the repo root)

Builds each @test_level, parses the bytes back and checks every slope (87
gentle, 88 steep) in both areas: steep w = h + 1, gentle w = 2h, at least
two rows tall, and no ground tile on the cells its surface owns.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv, _argv = ['x'], sys.argv
import gen_test_levels as gen  # noqa: E402
import parse_course as pc  # noqa: E402
sys.argv = _argv

SLOPES = {gen.OBJ_SLIGHT_SLOPE: False, gen.OBJ_STEEP_SLOPE: True}


class SlopeRecords(unittest.TestCase):
    def test_every_level(self):
        seen = 0
        for slot, (name, builder) in sorted(gen.TEST_LEVELS.items()):
            course = pc.parse_course(builder().build())
            for area in ('overworld', 'subworld'):
                tiles = {(t['x'], t['y']) for t in course[area]['tiles']}
                for a in course[area]['actors']:
                    if a['type'] not in SLOPES:
                        continue
                    seen += 1
                    steep = SLOPES[a['type']]
                    x, y, w, h = int(a['x'] // 16), int(a['y'] // 16), a['w'], a['h']
                    with self.subTest(slot=slot, name=name, area=area, at=(x, y)):
                        self.assertGreaterEqual(h, 2)
                        self.assertEqual(w, h + 1 if steep else 2 * h)
                        band = gen.slope_band(x, y, w, h, steep, bool(a['flags'] & gen.FLAG_DESCENDING))
                        self.assertEqual(len(band), 2 * w - 2)
                        self.assertEqual(sorted(band & tiles), [])
        self.assertGreater(seen, 0)

    def test_preflight_refuses(self):
        def course(*objects, ground=()):
            b = gen.LevelBuilder("x")
            b.objects += [{'x': 12, 'y': 4, 'flags': 0x06000040, **o} for o in objects]
            b.ground_tiles += ground
            return b
        for b, why in [
            (course({'id': gen.OBJ_STEEP_SLOPE, 'width': 4, 'height': 4}), 'not 5 wide'),
            (course({'id': gen.OBJ_SLIGHT_SLOPE, 'width': 6, 'height': 4}), 'not 8 wide'),
            (course({'id': gen.OBJ_STEEP_SLOPE, 'width': 2, 'height': 1}), 'under two rows'),
            (course({'id': gen.OBJ_STEEP_SLOPE, 'width': 5, 'height': 4}, ground=[(13, 4)]), 'ground on its surface'),
        ]:
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                b.preflight()


if __name__ == '__main__':
    unittest.main()
