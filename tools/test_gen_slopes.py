"""Every generated course's slope records are ones the game writes.

    python3 -m unittest tools/test_gen_slopes.py   (from the repo root)

Builds each @test_level, parses the bytes back and checks every slope (87
gentle, 88 steep) in both areas: steep w = h + 1, gentle w = 2h, at least
two rows tall, no ground tile on the cells its surface owns, and the ground
beside it tiled with its surface counted as ground, as the editor does.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv, _argv = ['x'], sys.argv
import autotile  # noqa: E402
import gen_test_levels as gen  # noqa: E402
import parse_course as pc  # noqa: E402
sys.argv = _argv

SLOPES = (gen.OBJ_SLIGHT_SLOPE, gen.OBJ_STEEP_SLOPE)


def built_areas():
    """(slot, name, area, tiles {(x, y): id}, slopes, outside) per area of every course."""
    for slot, (name, builder) in sorted(gen.TEST_LEVELS.items()):
        b = builder()
        course = pc.parse_course(b.build())
        for area, outside in (('overworld', b.unrecorded),
                              ('subworld', lambda x, y, b=b: gen._beyond(x, y, b.sub_width, b.sub_height))):
            tiles = {(t['x'], t['y']): t['id'] for t in course[area]['tiles']}
            slopes = [(int(a['x'] // 16), int(a['y'] // 16), a['w'], a['h'], a['type'] == gen.OBJ_STEEP_SLOPE,
                       bool(a['flags'] & gen.FLAG_DESCENDING))
                      for a in course[area]['actors'] if a['type'] in SLOPES]
            yield slot, name, area, tiles, slopes, outside


class SlopeRecords(unittest.TestCase):
    def test_every_level(self):
        seen = 0
        for slot, name, area, tiles, slopes, _ in built_areas():
            for slope in slopes:
                seen += 1
                x, y, w, h, steep, _ = slope
                with self.subTest(slot=slot, name=name, area=area, at=(x, y)):
                    self.assertGreaterEqual(h, 2)
                    self.assertEqual(w, h + 1 if steep else 2 * h)
                    surface = autotile.slope_surface(*slope)
                    self.assertEqual(len(surface), 2 * w - 2)
                    self.assertEqual(sorted(surface & tiles.keys()), [])
        self.assertGreater(seen, 0)

    def test_ground_beside_slopes(self):
        """Each ground tile next to a slope's surface has the id the editor
        gives it with the surface counted as ground."""
        changed = 0
        for slot, name, area, tiles, slopes, outside in built_areas():
            surface = set().union(*(autotile.slope_surface(*s) for s in slopes))
            beside = {(x + dx, y + dy) for (x, y) in surface for dx in (-1, 0, 1) for dy in (-1, 0, 1)} & tiles.keys()
            if not beside:
                continue
            want = autotile.autotile_ground(tiles, outside, slopes)
            without = autotile.autotile_ground(tiles, outside)
            for cell in sorted(beside):
                with self.subTest(slot=slot, name=name, area=area, at=cell):
                    self.assertEqual(tiles[cell], want[cell])
                changed += want[cell] != without[cell]
        self.assertGreater(changed, 0)

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
