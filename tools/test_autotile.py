"""Ground ids beside a slope, against a course the game's editor saved.

    python3 -m unittest tools/test_autotile.py   (from the repo root)

data/steep_slope_editor_033.json is parse_course.py --json of the editor's
own save of a steep slope course (an 8x7 steep slope on a two-row floor,
a column of ground behind it).
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from autotile import autotile_ground, slope_surface  # noqa: E402

COURSE = os.path.join(HERE, '..', 'data', 'steep_slope_editor_033.json')
FIRST_TILESET_ID = 24     # below it, the editor's decorative look-alikes
DESCENDS = 0x100000


class EditorSlopeCourse(unittest.TestCase):
    def setUp(self):
        with open(COURSE) as f:
            course = json.load(f)
        head, area = course['header'], course['overworld']
        width, height = area['bound_right'] // 16, area['bound_top'] // 16
        self.tiles = {(t['x'], t['y']): t['id'] for t in area['tiles']}
        # Record positions are tile centres in units of 16 per tile.
        self.slopes = [(int(a['x'] - 8) // 16, int(a['y'] - 8) // 16, a['w'], a['h'],
                        a['type'] == 88, bool(a['flags'] & DESCENDS))
                       for a in area['actors'] if a['type'] in (87, 88)]
        self.assertEqual(self.slopes, [(9, 1, 8, 7, True, False)])

        def outside(x, y):   # start area, goal area, past the area's edges
            return ((x < 7 and y < head['start_y']) or (x >= width - 10 and y < head['goal_y'])
                    or x < 0 or x >= width or y >= height)
        self.outside = outside

    def test_ids_match_the_editor(self):
        ids = autotile_ground(self.tiles, self.outside, self.slopes)
        tileset = {p: i for p, i in self.tiles.items() if i >= FIRST_TILESET_ID}
        self.assertEqual(len(tileset), 82)
        self.assertEqual({p: ids[p] for p in tileset}, tileset)

    def test_a_slope_surface_steps_one_row_per_column(self):
        self.assertEqual(slope_surface(0, 0, 3, 2, steep=True),
                         {(0, 0), (1, 0), (1, 1), (2, 1)})
        self.assertEqual(slope_surface(0, 0, 4, 2, steep=False, descending=True),
                         {(3, 0), (2, 0), (2, 1), (1, 0), (1, 1), (0, 1)})


if __name__ == '__main__':
    unittest.main()
